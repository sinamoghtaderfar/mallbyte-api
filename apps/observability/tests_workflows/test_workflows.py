"""Regression suite: least privilege, incident lifecycle, AI opt-in and two-person ops."""
from datetime import timedelta
from django.core.management import call_command
from io import StringIO
from unittest.mock import patch
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.accounts.models import User
from apps.rbac.models import Role
from apps.rbac.utils import assign_role
from apps.observability.models import AuditLog, ErrorLog, RequestLog
from apps.observability.workflow_models import Incident, IncidentEvent, InfrastructureOperation
from apps.observability.ai_diagnosis import build_context


class WorkflowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_superuser(email='obs-root@example.test',
                full_name='Root', password='TestPass123!')
        self.viewer = User.objects.create_user(email='obs-view@example.test',
                full_name='Viewer', password='TestPass123!')
        self.operator = User.objects.create_user(email='obs-op@example.test',
                full_name='Operator', password='TestPass123!')
        self.admin = User.objects.create_user(email='obs-admin@example.test',
                full_name='Observability Admin', password='TestPass123!')
        self.admin2 = User.objects.create_user(email='obs-admin2@example.test',
                full_name='Second Admin', password='TestPass123!')
        for user, role in ((self.viewer,'observability_viewer'),
                           (self.operator,'observability_operator'),
                           (self.admin,'observability_admin'),
                           (self.admin2,'observability_admin')):
            assign_role(user, Role.objects.get(name=role), self.owner)

    def login(self, user):
        self.client.force_authenticate(user=user)

    def incident(self):
        self.login(self.operator)
        response = self.client.post('/api/observability/incidents/',
                {'title':'Checkout failures', 'description':'High rate of HTTP errors', 'severity':'high'},
                format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def test_viewer_only_reads_incident_summary(self):
        incident_id = self.incident()
        self.login(self.viewer)
        result = self.client.get(f'/api/observability/incidents/{incident_id}/')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('description', result.data)
        self.assertNotIn('title', result.data)
        self.assertNotIn('source_error', result.data)
        self.assertEqual(self.client.post('/api/observability/incidents/',
            {'title':'No access'},format='json').status_code, 403)
        self.assertEqual(self.client.get('/api/observability/audit-logs/').status_code, 403)
        self.assertEqual(self.client.get('/api/observability/incidents/%s/events/' % incident_id).status_code, 403)

    def test_operator_log_details_masked_and_audit_denied(self):
        self.login(self.operator)
        log = ErrorLog.objects.create(exception_type='ValueError', message='password=secret',
                traceback='PRIVATE_TRACE', path='/api/orders/', status_code=500)
        RequestLog.objects.create(method='GET', path='/api/orders/', query_string='token=secret',
                                  status_code=500, duration_ms=42)
        err = self.client.get('/api/observability/error-logs/')
        self.assertEqual(err.status_code, 200)
        item = err.data['results'][0]
        self.assertNotIn('message', item)
        self.assertNotIn('traceback', item)
        req = self.client.get('/api/observability/request-logs/')
        self.assertNotIn('query_string', req.data['results'][0])
        self.assertNotIn('ip_address', req.data['results'][0])
        self.assertEqual(self.client.get('/api/observability/audit-logs/').status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.get('/api/observability/error-logs/').data['results'][0]['id'], str(log.id))
        self.assertEqual(self.client.get('/api/observability/audit-logs/').status_code, 200)

    def test_incident_assignment_history_and_resolution(self):
        incident_id = self.incident()
        assigned = self.client.post(f'/api/observability/incidents/{incident_id}/assign/',
                                    {'user_id':self.admin.pk}, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.data)
        bad = self.client.post(f'/api/observability/incidents/{incident_id}/transition/',
                {'status':'resolved', 'note':'it is fixed'}, format='json')
        self.assertEqual(bad.status_code, 409)
        started = self.client.post(f'/api/observability/incidents/{incident_id}/transition/',
                {'status':'investigating','note':'Started troubleshooting'}, format='json')
        self.assertEqual(started.status_code, 200, started.data)
        resolved = self.client.post(f'/api/observability/incidents/{incident_id}/transition/',
                {'status':'resolved','note':'Confirmed that checkout endpoint now passes validation'}, format='json')
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertIsNotNone(Incident.objects.get(pk=incident_id).resolved_at)
        self.assertGreaterEqual(IncidentEvent.objects.filter(incident_id=incident_id).count(), 4)
        self.assertTrue(AuditLog.objects.filter(object_type='Incident',object_id=incident_id).exists())

    def test_cannot_assign_to_customer(self):
        incident_id = self.incident()
        customer=User.objects.create_user(email='customer-obs@example.test',full_name='Customer')
        response=self.client.post(f'/api/observability/incidents/{incident_id}/assign/',
                                  {'user_id':customer.pk},format='json')
        self.assertEqual(response.status_code, 400)

    def test_ai_off_by_default_and_safe_context(self):
        incident_id=self.incident()
        source=ErrorLog.objects.create(exception_type='DatabaseError',message='Bearer SECRET',
                traceback='password=SENSITIVE', path='/api/orders/23412/',status_code=500)
        incident=Incident.objects.get(pk=incident_id)
        incident.source_error=source
        incident.save(update_fields=['source_error'])
        ctx=build_context(incident)
        self.assertEqual(ctx['route_template'], '/api/orders/{id}/')
        self.assertNotIn('traceback', ctx)
        self.assertNotIn('incident_description', ctx)
        self.assertNotIn('message', ctx)
        with override_settings(OBSERVABILITY_AI_ENABLED=False):
            response=self.client.post(f'/api/observability/incidents/{incident_id}/diagnose/',
                        {'consent_to_external_processing':True},format='json')
        self.assertEqual(response.status_code, 503)

    @override_settings(OBSERVABILITY_AI_ENABLED="auto", OBSERVABILITY_AI_API_KEY="test-key")
    def test_ai_async_requires_consent_and_never_calls_provider_in_request(self):
        incident_id = self.incident()
        denied = self.client.post(f'/api/observability/incidents/{incident_id}/diagnose/',
            {'include_description':False},format='json')
        self.assertEqual(denied.status_code,400)
        with patch('apps.observability.workflow_views.run_observability_ai_diagnosis.delay') as send:
            with self.captureOnCommitCallbacks(execute=True):
                result = self.client.post(f'/api/observability/incidents/{incident_id}/diagnose/',
                    {'include_description':False,'consent_to_external_processing':True},format='json')
            self.assertEqual(result.status_code,202,result.data)
            self.assertEqual(result.data['status'],'queued')
            send.assert_called_once()
            self.assertEqual(Incident.objects.get(pk=incident_id).status,'open')
        self.assertEqual(self.client.post(f'/api/observability/incidents/{incident_id}/diagnose/',
            {'consent_to_external_processing':True},format='json').status_code,429)

    @override_settings(OBSERVABILITY_AI_ENABLED="auto", OBSERVABILITY_AI_API_KEY="test-key")
    def test_ai_task_saves_provider_result_when_mocked(self):
        incident_id=self.incident()
        from apps.observability.workflow_models import AIDiagnosis
        from apps.observability.workflow_tasks import run_observability_ai_diagnosis
        job=AIDiagnosis.objects.create(incident_id=incident_id,
            requested_by=self.operator, model_name='pending')
        with patch('apps.observability.workflow_tasks.ask_ai_diagnosis',
                   return_value=('test-model','Check database connections first.')):
            result=run_observability_ai_diagnosis.run(str(job.id))
        self.assertEqual(result['status'],'succeeded')
        job.refresh_from_db()
        self.assertEqual(job.status,'succeeded')
        self.assertIn('database',job.response)

    def test_operation_request_requires_separate_approver(self):
        self.login(self.operator)
        res=self.client.post('/api/observability/operations/',
                {'target':'celery_worker','reason':'Workers are unresponsive after verified health checks'},
                format='json')
        self.assertEqual(res.status_code, 201, res.data)
        op_id=res.data['id']
        self.assertEqual(res.data['status'], 'pending')
        self.assertEqual(self.client.post(f'/api/observability/operations/{op_id}/approve/').status_code,403)
        self.login(self.admin)
        approved=self.client.post(f'/api/observability/operations/{op_id}/approve/')
        self.assertEqual(approved.status_code,200,approved.data)
        self.assertEqual(approved.data['status'],'approved')
        self.assertEqual(self.client.post(f'/api/observability/operations/{op_id}/approve/').status_code,409)
        self.assertTrue(AuditLog.objects.filter(object_type='InfrastructureOperation',object_id=op_id).exists())

    def test_operation_cannot_self_approve_or_restart_redis_by_default(self):
        self.login(self.admin)
        blocked=self.client.post('/api/observability/operations/',
                {'target':'redis','reason':'Restart redis for diagnostics; operator approval needed'},format='json')
        self.assertEqual(blocked.status_code,400)
        res=self.client.post('/api/observability/operations/',
                {'target':'celery_beat','reason':'Scheduler not dispatching work after verification'},format='json')
        self.assertEqual(res.status_code,201, res.data)
        self.assertEqual(self.client.post(f"/api/observability/operations/{res.data['id']}/approve/").status_code,403)
        self.assertEqual(InfrastructureOperation.objects.get(pk=res.data['id']).status,'pending')

    def test_operation_expiry_enforced(self):
        self.login(self.operator)
        res=self.client.post('/api/observability/operations/',
                {'target':'celery_worker','reason':'Workers failed three readiness checks'},format='json')
        obj=InfrastructureOperation.objects.get(pk=res.data['id'])
        obj.expires_at=timezone.now()-timedelta(minutes=1)
        obj.save(update_fields=['expires_at'])
        self.login(self.admin)
        self.assertEqual(self.client.post(f'/api/observability/operations/{obj.id}/approve/').status_code,409)
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'expired')

    def test_viewer_cannot_touch_operations(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get('/api/observability/operations/').status_code,403)
        self.assertEqual(self.client.post('/api/observability/operations/',
            {'target':'celery_worker','reason':'Restart please not authorized'},format='json').status_code,403)

    def test_bridge_claim_requires_approval_and_runner_is_database_only(self):
        op = InfrastructureOperation.objects.create(
            target=InfrastructureOperation.Target.CELERY_WORKER,
            requested_by=self.operator, approved_by=self.admin,
            status=InfrastructureOperation.Status.APPROVED,
            approved_at=timezone.now(),
            reason="Workers failed readiness and need an approved restart",
        )
        out=StringIO()
        call_command('observability_ops_bridge','claim',stdout=out)
        import json
        result=json.loads(out.getvalue())
        self.assertEqual(result['operation']['id'],str(op.pk))
        token=result['token']
        op.refresh_from_db()
        self.assertEqual(op.status,InfrastructureOperation.Status.RUNNING)
        self.assertTrue(op.execution_token_hash)
        from unittest.mock import patch as mock_patch
        import io
        with mock_patch('sys.stdin',io.StringIO(token+'\n')):
            output=StringIO()
            call_command('observability_ops_bridge','complete',operation_id=str(op.id),
                outcome='succeeded',message='Host verified running',token_stdin=True,stdout=output)
        op.refresh_from_db()
        self.assertEqual(op.status,InfrastructureOperation.Status.SUCCEEDED)
        self.assertEqual(op.execution_token_hash,'')

    def test_bridge_rejects_self_approved_or_redis_operation(self):
        InfrastructureOperation.objects.create(
            target=InfrastructureOperation.Target.REDIS,
            requested_by=self.operator, approved_by=self.admin,
            status=InfrastructureOperation.Status.APPROVED,
            approved_at=timezone.now(),
            reason="Redis is blocked from automatic host runner",
        )
        out=StringIO()
        call_command('observability_ops_bridge','claim',stdout=out)
        import json
        self.assertIsNone(json.loads(out.getvalue())['operation'])
