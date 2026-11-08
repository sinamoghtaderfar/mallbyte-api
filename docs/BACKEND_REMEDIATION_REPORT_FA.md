# گزارش وضعیت بازبینی و اصلاح Mallbyte Backend

تاریخ checkpoint: ۲۰۲۶-۱۱-۰۸. دامنه: فقط repository بک‌اند؛ Django/DRF، PostgreSQL، Redis و Celery. اتصال درگاه پرداخت خارجی خارج از دامنه است و نبود آن نقص محسوب نشده است. منطق داخلی پرداخت، بازپرداخت، سفارش و دفتر مالی بررسی و اصلاح شده است.

## نتیجهٔ اجرایی و محدودهٔ شواهد

در زمان تهیهٔ این checkpoint، ۳۴ PR شمارهٔ ۱۷ تا ۵۰ باز و بدون merge هستند. `main` و `origin/main` روی `0f70f2dbb379d2c9192319bb6dd9c44c00821fb0` باقی مانده‌اند؛ worktree اصلی پاک است. هیچ تغییر production، ادغام PR، force-push یا تغییر frontend انجام نشده است. اصلاحات در feature/fix branchهای مجزا نگهداری شده‌اند و وابستگی پشته‌ها ثبت شده است.

کاندیدای ترکیبی محلی برای آزمون، شاخهٔ `verify/remediation-integration` است؛ checkpoint اولیه `ce349e1c2ef180c787a682a3865a950666a5325c` و checkpoint تکمیلی schema/shipping برابر `6b6e996` است. این شاخه ابزار بررسی سازگاری PRهاست و برای merge یا انتشار ارسال نشده است. مسیرها و شماره‌خط‌های شواهد جدول ۴۴محوری به کاندیدای اولیه اشاره دارند؛ با تغییر commit ممکن است شماره‌خط جابه‌جا شود. برای بررسی تاریخی، diff همان PR مرجع نهایی است.

**آمادگی فعلی:** کاندیدای اصلاح‌شده برای تست دستی و استقرار کنترل‌شده در staging قابل بررسی است؛ production تأیید نشده است. خود `main` هنوز این اصلاحات را ندارد و برای اعلام آمادگی باید PRها پس از بازبینی و CI ادغام شوند. کار P3 قرارداد OpenAPI در PR49 منتشر شده و اصلاح P1 جدید وضعیت نهایی سفارش در PR50 به‌صورت مستقل آماده شده است. این دو نیز باید در ترتیب review/merge لحاظ شوند.

## ارزیابی معماری

ساختار فعلی یک monolith ماژولار Django است: دامنه‌های accounts/RBAC، catalog/reviews، inventory/cart/orders، payments/returns/shipping/settlements، support/notifications، content/analytics و observability جدا شده‌اند. برای این مقیاس، ادامهٔ همین معماری با serviceهای تراکنشی و قیود پایگاه داده مناسب است. نقص‌های اصلی کشف‌شده در مرز مجوز، اتمیک نبودن عملیات چندمدلی، رقابت همزمان، قرارداد API و بازیابی کار پس‌زمینه بوده‌اند.

اصلاحات جدید دسترسی تجاری را از `is_staff` جدا می‌کنند، تصمیم‌های مالی و موجودی را زیر lock و transaction می‌برند، یکتایی/سقف‌ها را در DB تقویت می‌کنند، و صف را با claim/lease و replay تحمل‌پذیر می‌سازند. این الگو از وابستگی امنیتی به cache و تضمین کاذب exactly-once صف اجتناب می‌کند. برخی helperهای قدیمی پاک‌سازی cache برای سازگاری rolling upgrade حفظ شده‌اند؛ نتیجهٔ مجوز از cache قدیمی خوانده نمی‌شود. بازنویسی کامل معماری یا تقسیم به microservice برای رفع یافته‌های تأییدشده لازم نیست.

## PRها، وابستگی‌ها و اعتبارسنجی

اعداد ستون آزمون، اجراهای هدفمند هر PR هستند و ممکن است با یکدیگر هم‌پوشانی داشته باشند؛ نباید آن‌ها را برای افزایش شمار تست‌ها جمع کرد. جمع مستقل اجرای نهایی در بخش آزمون آمده است. «اصلاح‌شده» در این گزارش یعنی پیاده‌سازی و commit/push در PR باز، نه اعمال در production.

| PR | اولویت | parent فعلی | branch | head در checkpoint | اصلاح انجام‌شده | اعتبارسنجی ثبت‌شده |
|---|---|---|---|---|---|---|
| [#17](https://github.com/sinamoghtaderfar/mallbyte-api/pull/17) | P0 | `main` | `fix/p0-stock-concurrency` | `766b4036` | قفل موجودی؛ جلوگیری از overwrite با مدل قدیمی؛ حفظ تاریخچهٔ انبار | ۷۴ PostgreSQL و آزمون رقابت |
| [#18](https://github.com/sinamoghtaderfar/mallbyte-api/pull/18) | P2 | `main` | `fix/p2-operational-safety` | `688869cc` | انتخاب صریح محیط در runner؛ محدودیت زمان؛ تثبیت آزمون replay MFA | ۴ آفلاین + ۹ MFA؛ CI کامل ۷۵۶ تست |
| [#19](https://github.com/sinamoghtaderfar/mallbyte-api/pull/19) | P0 | `main` | `fix/p0-account-prehijacking` | `fb8bc3e8` | اثبات مالکیت ایمیل پیش از صدور نشست؛ مهار حساب موقت | ۶۸ PostgreSQL |
| [#20](https://github.com/sinamoghtaderfar/mallbyte-api/pull/20) | P0 | `main` | `fix/p0-notification-authorization` | `be77feec` | مالکیت اعلان و ورودی/عملیات bulk محدود و اتمیک | ۷۴ PostgreSQL |
| [#21](https://github.com/sinamoghtaderfar/mallbyte-api/pull/21) | P2 | `main` | `fix/p2-proxy-client-ip` | `6f1b8fa6` | IP معتبر فقط از proxy معتمد، شامل ثبت audit | ۲۴ آزمون هدفمند |
| [#22](https://github.com/sinamoghtaderfar/mallbyte-api/pull/22) | P1 | `main` | `chore/p1-security-dependencies` | `3d575102` | به‌روزرسانی وابستگی‌های آسیب‌پذیر؛ audit کل production requirements | pip check و pip-audit موفق؛ CI audit سبز |
| [#23](https://github.com/sinamoghtaderfar/mallbyte-api/pull/23) | P2 | `main` | `fix/p2-recovery-client-compatibility` | `68387ffe` | رد نسخهٔ ناسازگار client PostgreSQL پیش از restore | ۴ آفلاین + drill واقعی backup/restore PostgreSQL16 |
| [#24](https://github.com/sinamoghtaderfar/mallbyte-api/pull/24) | P3 | `main` | `chore/p3-observability-quality` | `7cff257c` | رفع lint observability و تنظیمات تکراری | ۷۹ تست؛ CI سبز |
| [#25](https://github.com/sinamoghtaderfar/mallbyte-api/pull/25) | P0 | `main` | `fix/p0-private-media` | `354fb193` | دانلود مجاز و خصوصی گزارش مالی و مدارک مرجوعی | ۱۵۹ PostgreSQL + ۴ آزمون حریم خصوصی |
| [#26](https://github.com/sinamoghtaderfar/mallbyte-api/pull/26) | P0 | #19 | `fix/p0-session-revocation` | `fd54d78c` | ابطال نشست با رویداد امنیتی؛ حفظ security epoch در stale save | ۷۹ PostgreSQL |
| [#27](https://github.com/sinamoghtaderfar/mallbyte-api/pull/27) | P1 | `main` | `fix/p1-catalog-moderation` | `05357bda` | بازگشت تغییرات محصول/نظر به moderation؛ حذف افشای دادهٔ عمومی | ۵۹ PostgreSQL |
| [#28](https://github.com/sinamoghtaderfar/mallbyte-api/pull/28) | P2 | #48 | `fix/p2-return-evidence-workflow` | `b5dc1e44` | آپلود مدرک خصوصی و ثبت tracking توسط صاحب مرجوعی | ۳۰ PostgreSQL؛ در گروه ترکیبی ۱۰۰ تست نیز پوشش دارد |
| [#29](https://github.com/sinamoghtaderfar/mallbyte-api/pull/29) | P1 | #26 | `fix/p1-identity-workflows` | `a52a9896` | مصرف اتمیک OTP؛ اثبات مقصد تغییر ایمیل؛ validators صحیح رمز | ۹۱ PostgreSQL |
| [#30](https://github.com/sinamoghtaderfar/mallbyte-api/pull/30) | P1 | `main` | `fix/p1-financial-audit-recovery` | `d057ce6e` | بازیابی audit مالی با lease و fencing و retry محدود | ۳۷ PostgreSQL شامل ۷ تست تازه |
| [#31](https://github.com/sinamoghtaderfar/mallbyte-api/pull/31) | P1 | #35 | `fix/p1-analytics-correctness` | `60613f37` | بازهٔ درست گزارش، dispatch پس از commit، بازیابی worker و CSV ایمن | گروه ترکیبی analytics: ۱۴۴ PostgreSQL |
| [#32](https://github.com/sinamoghtaderfar/mallbyte-api/pull/32) | P0 | #17 | `fix/p0-checkout-idempotency` | `631dd3d` | checkout اتمیک/idempotent، تعرفهٔ سرور، انقضای رزرو | ۴۰ PostgreSQL + ۱۲ هدفمند |
| [#33](https://github.com/sinamoghtaderfar/mallbyte-api/pull/33) | P0 | #29 | `fix/p0-rbac-permissions` | `dd3cdaf7` | مجوزهای صریح حساب/فروشنده؛ تصمیم و درخواست فروشنده اتمیک | ۱۵۶ PostgreSQL + ۲۴ seller؛ CI سبز |
| [#34](https://github.com/sinamoghtaderfar/mallbyte-api/pull/34) | P2 | #25 | `fix/p2-private-media-migration` | `9028d9e1` | تأیید SHA256 پیش از حذف نسخهٔ عمومی attachment قدیمی | ۳ آزمون فایل‌سیستم |
| [#35](https://github.com/sinamoghtaderfar/mallbyte-api/pull/35) | P2 | #27 | `fix/p2-catalog-integrity-performance` | `e91f3e04` | قیود کاتالوگ، nested write اتمیک، import محدود و queries بهینه | ۷۴ PostgreSQL + آزمون خطای شناسه؛ گروه ترکیبی پوشش دارد |
| [#36](https://github.com/sinamoghtaderfar/mallbyte-api/pull/36) | P1 | #33 | `fix/p1-support-transitions` | `2bb69837` | تغییر وضعیت تیکت همراه audit/notification اتمیک؛ تاریخچهٔ محدود | ۶۷ PostgreSQL |
| [#37](https://github.com/sinamoghtaderfar/mallbyte-api/pull/37) | P0 | #25 | `fix/p0-refund-consistency` | `827cc7b8` | سقف بازپرداخت خالص تخفیف‌خورده؛ الزام مدرک معتبر؛ همگامی وضعیت‌ها | ۶۸ PostgreSQL شامل رقابت و ۱۴ تست تازه |
| [#38](https://github.com/sinamoghtaderfar/mallbyte-api/pull/38) | P3 | #24 | `chore/p3-repository-quality` | `65da3d0c` | گسترش lint و CI به PRهای پشته‌ای؛ تثبیت آزمون MFA | ۴۳ content + بررسی Ruff/AST؛ CI سبز |
| [#39](https://github.com/sinamoghtaderfar/mallbyte-api/pull/39) | P0 | #33 | `fix/p0-commerce-permissions` | `37ee9efa` | مجوز صریح عملیات سفارش/پرداخت/ارسال/مرجوعی؛ حذف metadata داخلی | ۹۱ PostgreSQL شامل ۱۲ تست تازه |
| [#40](https://github.com/sinamoghtaderfar/mallbyte-api/pull/40) | P2 | #29 | `fix/p2-default-addresses` | `ad5d5a00` | آدرس پیش‌فرض اتمیک و constraint یکتا | ۹۸ PostgreSQL |
| [#41](https://github.com/sinamoghtaderfar/mallbyte-api/pull/41) | P1 | #33 | `fix/p1-admin-privilege-boundaries` | `0db24a28` | جلوگیری از ارتقای دسترسی از Django admin برای staff واگذارشده | ۱۰۱ PostgreSQL |
| [#42](https://github.com/sinamoghtaderfar/mallbyte-api/pull/42) | P2 | #38 | `fix/p2-content-query-integrity` | `5eb027b2` | queries محدود CMS، validation شناسه و بررسی مجوز پس از lock | ۵۳ PostgreSQL؛ بازاجرای ترکیبی catalog/CMS: ۱۳۴ موفق |
| [#43](https://github.com/sinamoghtaderfar/mallbyte-api/pull/43) | P0 | #26 | `fix/p0-mfa-challenge-revocation` | `45aafb8c` | ابطال چالش MFA باز با تغییر security epoch | ۸۸ PostgreSQL شامل ۹ تست تازه/رقابت |
| [#44](https://github.com/sinamoghtaderfar/mallbyte-api/pull/44) | P2 | #39 | `fix/p2-commerce-query-performance` | `ca10b86e` | pagination و prefetch سفارش فروشنده/ارسال؛ موجودی سبد منطبق با انبار فعال | ۴۷ orders/payments + ۵۱ shipping/returns؛ ۸ query |
| [#45](https://github.com/sinamoghtaderfar/mallbyte-api/pull/45) | P1 | #44 | `fix/p1-commerce-action-transactions` | `009e0282` | اتمیک بودن state، audit، notification و موجودی در actions مالی/ارسال | ۳۸ PostgreSQL شامل ۹ rollback |
| [#46](https://github.com/sinamoghtaderfar/mallbyte-api/pull/46) | P2 | #33 | `fix/p2-rbac-api-validation` | `1ee839a1` | validation سخت‌گیرانهٔ RBAC و serialization با queries محدود و ترتیب قطعی | ۹۹ PostgreSQL؛ ۸ تست تازه |
| [#47](https://github.com/sinamoghtaderfar/mallbyte-api/pull/47) | P2 | #35 | `fix/p2-saleable-stock` | `403eb67b` | موجودی قابل فروش فقط از انبار فعال و پس از کسر رزرو | ۸۱ PostgreSQL شامل ۶ تست تازه |
| [#48](https://github.com/sinamoghtaderfar/mallbyte-api/pull/48) | P1 | #37 | `feat/p1-return-inventory-restoration` | `7cb1107d` | بازگردانی صریح موجودی مرجوعی پس از تأیید قابل فروش بودن، با کلید تکرار | ۵۵ PostgreSQL شامل ۱۸ تازه و ۳ رقابت واقعی |

| [#49](https://github.com/sinamoghtaderfar/mallbyte-api/pull/49) | P3 | #38 | `fix/p3-openapi-contracts` | `4e5b105` | قراردادهای واقعی OpenAPI، JWT/MFA و فایل خصوصی؛ کشف خودکار تست config | ۱۷ schema و ۹ MFA موفق روی ترکیب PostgreSQL؛ تولید strict بدون هشدار |
| [#50](https://github.com/sinamoghtaderfar/mallbyte-api/pull/50) | P1 | #45 | `fix/p1-shipment-terminal-state` | `440e092` | حفظ state نهایی سفارش/fulfillment هنگام لغو parcel قدیمی | ۵ مورد شکست پیش از اصلاح؛ ۶ تست تازه و رگرسیون shipping/payment موفق |

شاخه‌ها و parentها در جدول آمده‌اند. headها مربوط به کد پیش از commit مستندات همین گزارش‌اند؛ تغییرات بعدی در PRها باید هنگام merge دوباره بررسی شوند. PR49 metadata به همهٔ runtimeها وابستگی کاربردی دارد و بهتر است پس از آن‌ها merge شود، هرچند parent رسمی آن PR38 است.

## پوشش یافته‌های ممیزی و شواهد کد

این جدول ۴۴ محور backlog اولیه را به تغییر قابل بازبینی متصل می‌کند. در هر ردیف، اثر نقص قبلی و اصلاح آن ذکر شده است. ردیف ۳۷ بخشی وابسته به دادهٔ واقعی و ردیف ۳۸ بخشی وابسته به محیط staging دارد؛ آن بخش‌ها با بررسی محلی بسته نمی‌شوند. شواهد زیر محل کنترل اصلاح‌شده‌اند؛ اصل نقص و تغییر دقیق را باید همراه diff PR مربوط خواند.

| محور | اثر نقص و اصلاح مشخص | شاهد در کاندیدای ترکیبی | PR / وضعیت |
|---|---|---|---|
| ۱ | تصاحب حساب با ثبت‌نام ایمیل دیگران؛ صدور نشست به اثبات ایمیل وابسته و رمز موقت حذف شد | `apps/accounts/views.py:74`، `apps/accounts/views.py:214` | #19؛ اصلاح‌شده |
| ۲ | قدرت تجاری ناخواستهٔ staff و ارتقای نقش؛ مجوزهای صریح API/admin و منع سیاست‌های سیستمی اعمال شد | `apps/rbac/commerce.py:8`، `apps/rbac/utils.py:24`، `apps/accounts/admin.py:212` | #33، #39، #41، #46؛ اصلاح‌شده |
| ۳ | بقای نشست/چالش MFA پس از رویداد امنیتی؛ security epoch در JWT و challenge بررسی و stale save محافظت شد | `apps/accounts/models.py:156`، `apps/accounts/mfa_views.py:55` | #26، #43؛ اصلاح‌شده |
| ۴ | دسترسی عمومی به گزارش مالی و مدرک مرجوعی؛ storage خصوصی، دانلود مجاز و انتقال با checksum | `apps/returns/private_media_views.py:18`، `apps/support/management/commands/migrate_private_media.py:74` | #25، #34؛ کد اصلاح‌شده؛ انتقال واقعی اجرا نشده |
| ۵ | overwrite شدن موجودی با ذخیرهٔ مدل قدیمی؛ update محدود و قفل موجودی | `apps/inventory/models.py:228` | #17؛ اصلاح‌شده |
| ۶ | checkout تکراری/رقابتی و snapshot ناسازگار سبد؛ lock مشترک و fingerprint کلید تکرار | `apps/orders/serializers.py:678`، `apps/orders/views.py:91` | #32؛ اصلاح‌شده |
| ۷ | اعتماد به هزینهٔ ارسال ورودی؛ تعرفه از تنظیمات سرور و تطبیق ورودی | `apps/orders/checkout_policy.py:14` | #32؛ اصلاح‌شده |
| ۸ | خرید محصول/فروشندهٔ فاقد شرایط؛ eligibility زیر قفل دوباره بررسی می‌شود | `apps/orders/serializers.py:697`، `apps/orders/serializers.py:724` | #32؛ اصلاح‌شده |
| ۹ | بازپرداخت بیش از سهم خالص بعد از تخفیف؛ تخصیص ثابت و سقف کمی/پولی و rounding نهایی | `apps/returns/services.py:120`، `apps/returns/services.py:174` | #37؛ اصلاح‌شده |
| ۱۰ | وضعیت refunded بدون مدرک و ناهماهنگی Payment/Order؛ الزام evidence معتبر حتی با ledger غیرفعال | `apps/returns/services.py:429`، `apps/returns/services.py:456` | #37، #45؛ اصلاح‌شده |
| ۱۱ | رزرو بی‌انقضا و گیر کردن موجودی؛ deadline، cleanup تکرارپذیر و جلوگیری از capture منقضی | `apps/orders/models.py:176`، `apps/orders/tasks.py:15` | #32؛ اصلاح‌شده |
| ۱۲ | حذف انبار و تخریب سابقه؛ حذف API محدود و FKهای تاریخی PROTECT شدند | `apps/inventory/models.py:141`، `apps/orders/models.py:435` | #17؛ اصلاح‌شده |
| ۱۳ | دور زدن moderation محصول؛ تغییر فروشنده approval را باطل و featured را محدود می‌کند | `apps/products/serializers.py:343` | #27؛ اصلاح‌شده |
| ۱۴ | انتشار و آمار نظر بدون مجوز/lock کافی؛ کنترل صریح و بازبینی پس از تغییر | `apps/reviews/views.py:77`، `apps/reviews/views.py:112` | #27؛ اصلاح‌شده |
| ۱۵ | مصرف چندباره/صدور موازی OTP؛ CAS و constraint یک کد استفاده‌نشده | `apps/accounts/models.py:312`، `apps/accounts/models.py:357` | #29؛ اصلاح‌شده |
| ۱۶ | نادیده گرفتن validators زمینه‌دار رمز؛ validate_password با user واقعی | `apps/accounts/serializers.py:362`، `apps/accounts/serializers.py:376` | #29؛ اصلاح‌شده |
| ۱۷ | تغییر ایمیل بدون اثبات مقصد یا یکتایی کافی؛ token محدود به مقصد/نسخه و unique case-insensitive | `apps/accounts/models.py:126`، `apps/accounts/views.py:777` | #29؛ اصلاح‌شده |
| ۱۸ | تصمیم/ثبت فروشندهٔ نیمه‌کاره و رقابتی؛ lock با ترتیب User→Seller و rollback یکپارچه | `apps/accounts/models.py:474`، `apps/accounts/views.py:264` | #33؛ اصلاح‌شده |
| ۱۹ | تغییر وضعیت تیکت جدا از پیام/audit؛ transaction و lock مشترک | `apps/support/views.py:158`، `apps/support/views.py:430` | #36؛ اصلاح‌شده |
| ۲۰ | بازهٔ اشتباه گزارش یا تغییر آن در retry؛ بازهٔ صریح و anchor زمان ایجاد | `apps/analytics/services.py:79`، `apps/analytics/tasks.py:44` | #31؛ اصلاح‌شده |
| ۲۱ | dispatch قبل از commit و کار گم‌شده؛ on_commit و redelivery از رکورد پایدار | `apps/analytics/tasks.py:140`، `apps/analytics/tasks.py:149` | #31؛ اصلاح‌شده |
| ۲۲ | audit مالی گیرکرده/worker قدیمی؛ lease، fencing و retry محدود با کلید ثابت | `apps/settlements/monitoring.py:24`، `apps/settlements/tasks.py:58` | #30؛ اصلاح‌شده |
| ۲۳ | آسیب‌پذیری وابستگی‌ها؛ نسخه‌های اصلاح‌شده و audit دامنهٔ production | `requirements/base.txt:2`، `.github/workflows/dependency-security.yml:1` | #22؛ اصلاح‌شده؛ نتایج audit مربوط به زمان اجراست |
| ۲۴ | افشای دادهٔ فروشنده/هزینه و wishlist نامحدود؛ projection عمومی محدود و مالکیت | `apps/products/serializers.py:130`، `apps/products/serializers.py:375` | #27؛ اصلاح‌شده |
| ۲۵ | دادهٔ نامعتبر کاتالوگ و nested write ناقص؛ preflight، constraint و transaction | `apps/products/migrations/0011_catalog_integrity.py:8`، `apps/products/migrations/0011_catalog_integrity.py:122` | #35؛ اصلاح‌شده |
| ۲۶ | N+1 و پاسخ‌های نامحدود؛ aggregate/prefetch و pagination و سقف ورودی | `apps/products/querysets.py:12`، `apps/support/views.py:180`، `apps/content/views.py:277` | #35، #36، #42، #44، #46، #47؛ اصلاح‌شده |
| ۲۷ | bulk اعلان نامحدود و مالکیت ضعیف؛ ورودی حداکثر ۱۰۰۰ و update شرطی | `apps/notifications/views.py:49`، `apps/notifications/serializers.py:121` | #20؛ اصلاح‌شده |
| ۲۸ | تزریق فرمول در CSV/XLSX؛ sanitizer مشترک برای رشته و حفظ عدد واقعی | `apps/analytics/services.py:1185`، `apps/analytics/views.py:197` | #31؛ اصلاح‌شده |
| ۲۹ | تبدیل خطای دامنه/ورودی به500؛ validation مرزی و پاسخ400/409 پس از rollback | `apps/returns/customer_workflows.py:44`، `apps/orders/serializers.py:688` | #17، #33، #35، #37، #42، #46؛ اصلاح‌شده |
| ۳۰ | چند آدرس پیش‌فرض همزمان؛ lock مالک و unique جزئی DB | `apps/accounts/models.py:243`، `apps/accounts/models.py:278` | #40؛ اصلاح‌شده |
| ۳۱ | جعل IP و دور زدن throttle/audit؛ peer معتمد و header پاک‌سازی‌شدهٔ proxy | `apps/accounts/client_ip.py:13` | #21؛ اصلاح‌شده؛ proxy واقعی هنوز نیازمند آزمون است |
| ۳۲ | runner مبهم/عملیات نامحدود؛ محیط صریح و timeout | `deploy/observability_ops/host_runner.py:53` | #18؛ اصلاح‌شده |
| ۳۳ | QR signal ثبت‌نشده/خطای جانبی و اعلان low-stock تکراری؛ ثبت signal، بعد از commit و backfill | `apps/products/signals.py:18` | #35؛ اصلاح‌شده؛ backfill واقعی اجرا نشده |
| ۳۴ | نبود workflow مدرک/tracking مشتری؛ upload خصوصی مجاز و replay کنترل‌شده | `apps/returns/customer_workflows.py:55`، `apps/returns/customer_workflows.py:95` | #28؛ اصلاح‌شده |
| ۳۵ | نبود سیاست مشخص بازگردانی موجودی مرجوعی؛ سیاست انتخاب‌شدهٔ کاربر پیاده شد | `apps/returns/inventory_restoration.py:51`، `apps/returns/models.py:419` | #48؛ اصلاح‌شده |
| ۳۶ | تغییر state تجاری جدا از audit/notification؛ outer atomic روی actions | `apps/payments/views.py:116`، `apps/shipping/views.py:150` | #45؛ اصلاح‌شده |
| ۳۷ | migrationهای تاریخی حذف stock/Review بدون انتقال؛ تاریخچه بازنویسی نشده | `apps/products/migrations/0009_remove_product_stock.py:13`، `apps/products/migrations/0010_delete_review.py:13` | رفتار حذف تأییدشده؛ وجود/وسعت اتلاف واقعی نامشخص و وابسته به backup |
| ۳۸ | نبود شواهد اجرای DB/broker/recovery؛ PG، Redis/Celery و restore محلی اجرا شد | `docs/STAGING_AND_RECOVERY.md:81`؛ نتایج بخش آزمون | بخش محلی تکمیل؛ محیط staging/load هنوز تأییدنشده |
| ۳۹ | خطاهای lint و نگهداشت؛ Ruff کل کاندیدا پاک | `.github/workflows/static-quality.yml:1` | #24، #38؛ اصلاح‌شده |
| ۴۰ | import/config تکراری و ProductTag موازی؛ پاک‌سازی و انتقال union پیش از حذف جدول | `apps/products/migrations/0011_catalog_integrity.py:31` | #24، #35، #38؛ اصلاح‌شده |
| ۴۱ | قیمت variant ناسازگار با مبلغ فروش؛ final_price برابر selling price | `apps/products/models.py:324` | #35؛ اصلاح‌شده |
| ۴۲ | قرارداد/validation ناقص API؛ شناسه‌ها سخت‌گیرانه و قرارداد schema با انواع صریح تکمیل شده | `apps/rbac/views.py:207`، `apps/content/views.py:94` | #35، #42، #46، #49؛ اصلاح‌شده |
| ۴۳ | تست و CI شکننده/عدم اجرا روی parent غیرmain؛ replay زمان ثابت و workflow تمام baseها | `.github/workflows/backend-ci.yml:1`، `apps/rbac/views.py:205` | #18، #26، #38، #42؛ اصلاح‌شده |
| ۴۴ | کیفیت کلی و پوشش بین‌ماژولی؛ شواهد رگرسیون و runbook به‌روز | `docs/PRODUCTION_RUNBOOK.md:39` و جدول تست نهایی | اجرای runtime و قرارداد OpenAPI تکمیل؛ گیت‌های محیط باقی |

موردهای ۱ تا ۱۲ شامل ریسک‌های بحرانی/بالای تصاحب حساب، IDOR، ارتقای دسترسی، افشای فایل خصوصی و فساد موجودی/پول بودند. یافته‌های business workflow و بازیابی worker در ردهٔ بالا، validation/query/migration safety در ردهٔ متوسط، و lint/schema در ردهٔ پایین قرار می‌گیرند. اولویت اجرایی هر PR در جدول جداگانه آمده است؛ اولویت merge باید parentها را نیز رعایت کند.

## یافتهٔ تازه در بازبینی تکمیلی

این مورد افزوده بر ۴۴ محور backlog اولیه است: لغو یک Shipment قدیمی/باز ممکن بود fulfillment را به PAID برگرداند و سپس `Order.status` نهایی مانند refunded/cancelled/delivered را بازنویسی کند، درحالی‌که payment_status نهایی باقی می‌ماند. شاهد کاندیدای پیش از اصلاح: `apps/shipping/models.py:418` و `apps/shipping/models.py:444`. اثر، از بین رفتن سازگاری مالی/سفارش در پاک‌سازی parcel قدیمی است؛ اولویت P1 دارد. اصلاح مستقل در PR50 روی شاخهٔ `fix/p1-shipment-terminal-state`، بر پایهٔ PR45، آماده شده است: لغو parcel برای cleanup مجاز می‌ماند، اما همگام‌سازی state سفارش و fulfillment فقط برای سفارش paid و فعال انجام می‌شود. ۶ تست تازه این رفتار را پوشش می‌دهند؛ پیش از اصلاح ۵ مورد شکست خورد و پس از اصلاح هر۶ مورد موفق شدند. رگرسیون shipping/payment شامل۵۸ تست PostgreSQL روی شاخهٔ اصلاح و سپس اجرای۱۵۸ تست payment/shipping/returns/settlements روی کاندیدای ترکیبی هر دو موفق‌اند.

## سیاست موجودی مرجوعی که کاربر تصویب کرده است

PR48 صرفاً عملیات صریح اپراتور دارای `restock_returns` را فراهم می‌کند. مجوز در migration تعریف می‌شود و **به هیچ نقش خودکار داده نمی‌شود**. دریافت یا بازپرداخت به‌تنهایی موجودی قابل فروش را زیاد نمی‌کند. receipt ثبت‌شده، وضعیت مجاز آیتم/درخواست، `sellable_confirmed=true` واقعی JSON، مقدار مثبت، انبار فعال و سقف مجموع برگشت الزامی است. lockها با ترتیب Order→Return→Item→Warehouse→Stock گرفته می‌شوند. کلید تکراری با payload یکسان همان نتیجه را می‌دهد؛ payload متفاوت409 است. audit غیرقابل‌ویرایش به StockMovement نوع RETURN متصل می‌شود. هیچ وضعیت مالی با این عملیات تغییر نمی‌کند.

## نتایج واقعی آزمون و محدودیت‌ها

اجرای اولیهٔ ترکیبی روی PostgreSQL16، در ۹ فرمان با سقف ۵۵ ثانیه، **۹۹۳ تست متمایز موفق و بدون شکست** داشته است. این اجرا به‌تنهایی همهٔ تست‌های قابل کشف را شامل نمی‌شد؛ ۱۴ تست زیرماژول payment در label انتخاب‌شده کشف نشده بودند. شکاف با اجرای تکمیلی زیر بسته شد:

| بخش | شمار تست | فایل log محلی |
|---|---:|---|
| accounts | ۱۱۵ | `/tmp/mallbyte-final-accounts.log` |
| RBAC | ۱۰۸ | `/tmp/mallbyte-final-rbac.log` |
| inventory/orders/discounts | ۱۳۱ | `/tmp/mallbyte-final-stock-orders-discounts.log` |
| returns/settlements | ۱۰۰ | `/tmp/mallbyte-final-returns-settlements.log` |
| products/reviews/content | ۱۳۴ | `/tmp/mallbyte-final-catalog-cms-fixed.log` |
| analytics | ۱۴۴ | `/tmp/mallbyte-final-analytics.log` |
| payments/shipping | ۳۸ | `/tmp/mallbyte-final-payments-shipping.log` |
| support/notifications | ۱۴۴ | `/tmp/mallbyte-final-support-notifications.log` |
| observability/config | ۷۹ | `/tmp/mallbyte-final-observability-config.log` |

اجرای تکمیلی روی کاندیدای نهایی در `/tmp/mallbyte-final-commerce-closure.log` شامل **۱۵۸ تست موفق PostgreSQL در۱۹٫۹۵۵ثانیه** برای payments/shipping/returns/settlements بود: ۱۴ تست payment که از اجرای قبلی جا مانده بودند، ۶ تست تازهٔ وضعیت نهایی Shipment و ۱۳۸ تست رگرسیون تکراری. اجرای `/tmp/mallbyte-schema-combined-final-pg.log` نیز ۲۶ تست موفق داشت: ۱۷ تست تازهٔ قرارداد OpenAPI و ۹ تست رگرسیون MFA تکراری. بنابراین ۹ گروه اولیه + اجرای۱۵۸تایی + اجرای۲۶تایی، **۱۰۳۰ شناسهٔ تست runtime متمایز موفق PostgreSQL** را پوشش می‌دهند: ۹۹۳ + ۱۴ + ۶ + ۱۷؛ مجموع اجراهای این شواهد۱۱۷۷ است ولی۱۴۷ اجرای تکراری دوباره شمرده نشده‌اند. مجموعه با discovery پیش‌فرض `apps/config` تطبیق داده شد و شناسهٔ اجرا‌نشده باقی نماند؛ prefix مهاجرت که در ابتدای خط اولین تست هر log چاپ شده بود نیز در parser شواهد لحاظ شد. فایل `config/tests/__init__.py` در PR49 تست‌های تنظیمات/قرارداد را برای کشف خودکار CI قابل شناسایی می‌کند. این آمار حاصل چند اجرای رگرسیون روی checkpointهای ترکیبی است، نه ادعای یک اجرای کامل منفرد روی head نهایی.

۱۶ ماژول اصلی app در بررسی و رگرسیون لحاظ شده‌اند. **درصد coverage اندازه‌گیری نشده است**؛ تطبیق شناسه‌های تست کشف‌شده به معنی پوشش صددرصد مسیرهای کد نیست. fixture محدود CMS مستقل از migration seed اصلاح شد؛ انتشار محتوا همچنان برای نقش فاقد مجوز ممنوع است. MFA برای عبور تست ضعیف نشده است: فقط clock تست و replay همان کد تولیدشده ثابت شده‌اند.

۸ تست آفلاین ops نیز موفق‌اند (`ops.tests.test_postgres_client_check` و `deploy.observability_ops.test_host_runner`). علاوه بر آن:

- Ruff کل کاندیدا و parse کردن ۴۶۴ فایل Python موفق؛ migration drift در `makemigrations --check --dry-run` مشاهده نشد.
- Redis واقعی و Celery worker واقعی برای queued delivery پیش از startup، JSON transport و retry اجرا شد؛ task انقضای سفارش واقعاً موجودی را یک‌بار آزاد و Payment/Order را cancel کرد؛ daily audit در replay دوباره ثبت نشد. این آزمون eager نبود.
- backup/restore واقعی در سرویس disposable PostgreSQL16، با client16 و checksum، دادهٔ marker را بازگرداند. ناسازگاری client18 با server16 شناسایی و guard نسخه آزموده شد.
- `nginx -t` و `docker compose ... config --quiet` برای production/staging با env ساختگی و مجزا موفق؛ هیچ سرویس واقعی deploy نشد.
- `bash -n` اسکریپت‌های backup/restore/client-check موفق؛ `pip check` و `pip-audit` روی مجموعهٔ production بدون آسیب‌پذیری شناخته‌شده در زمان اجرا موفق؛ CI امنیت PR22 سبز است.
- کنترل‌های production برای cookie امن، TLS، CORS و غیرفعال بودن Django admin پیش‌فرض با env ساختگی موفق‌اند. `check --deploy` با `fail_level=WARNING` نیز بدون مسئله و با صفر مورد silenced گذشت (`/tmp/mallbyte-production-final-check.log`)؛ این بررسی اتصال به DB واقعی نداشت. هشدارهای OpenAPI checkpoint پیشین با قراردادهای واقعی schema اصلاح شدند؛ تولید schema در کاندیدای ترکیبی با `--validate --fail-on-warn` بدون خطا و هشدار موفق است. ۱۷ تست schema روی PostgreSQL بدون skip گذشتند؛ runtime authentication یا مجوزها برای حذف هشدار ضعیف نشده‌اند. Ruff ترکیبی و migration drift نیز پس از تغییر جدید پاک‌اند.

سرویس‌ها، DBها، رسانه و وابستگی‌های تست در مسیرها/پورت‌های موقت و مجزا بودند؛ harness فایل `.env` واقعی را بارگذاری نمی‌کند. hash سریع رمز فقط تنظیم تست است. هیچ داده یا فایل خصوصی اپراتور/production برای آزمون خوانده یا جابه‌جا نشده است. logهای `/tmp` artifact توسعه‌اند و برای شواهد بلندمدت باید توسط فرایند CI نگهداری شوند.

## وضعیت CI

در snapshot نهایی، هر۳۴ PR بازند؛ وضعیت merge همه CLEAN است، به‌جز PR49 که به علت درحال‌اجرابودن تست UNSTABLE نمایش داده می‌شود. هیچ check گزارش‌شده‌ای با نتیجهٔ شکست فعال نیست. PR49 پنج check موفق و تست Django درحال‌اجرا دارد؛ نتیجهٔ نهایی آن هنوز تأیید نشده است. PR50 به علت فیلتر قدیمی workflow روی base غیرmain، check گزارش‌شده ندارد. PR18 و PR33 که ابتدا شکست داشتند اکنون سبزند؛ علت مشترک، ساخت TOTP تازه در سوی دیگر مرز۳۰ثانیه و انتظار نادرست replay بود. اصلاح همان تست موجود بازاستفاده شد، نه تغییر قواعد MFA. اجرای موفق PR18: [run42494351765](https://github.com/sinamoghtaderfar/mallbyte-api/actions/runs/42494351765)، ۷۵۶ تست. PR38 در head کدی `65da3d0` و PR42 نیز همهٔ checkهای گزارش‌شده را موفق گذرانده‌اند. commit مستندات همین گزارش روی PR38 اجرای تازهٔ CI ایجاد می‌کند؛ نتیجهٔ سبز head قبلی نباید به head تازه نسبت داده شود.

تعدادی PR پشته‌ای check ندارند، زیرا workflow قدیمی فقط PR با base=`main` را اجرا می‌کرد. این وضعیت **سبز فرض نمی‌شود**. PR38 فیلتر base را اصلاح می‌کند؛ پس از merge parent و retarget کودک، CI باید دوباره روی head نهایی و ترکیب main اجرا شود. هشدار pagination مربوط به UserRole در log قدیمی PR18 در PR46 با ترتیب قطعی `-assigned_at,-pk` اصلاح شده است و نقص باز در کاندیدای ترکیبی نیست.

## migration و rollout بدون تغییر خودکار دادهٔ تجاری

migrationهای جدید/تغییریافتهٔ این مجموعه شامل accounts0016/0017/0018، rbac0014، inventory0005، orders0004/0005، analytics0002، returns0002/0003/0004، products0011 و settlements0003 هستند. شماره و dependency دقیق باید از graph نهایی پس از merge خوانده شود. پیش از اجرای واقعی، روی restore مستقل staging آزمون شوند؛ constraints جدید در صورت دادهٔ نامعتبر عمداً fail می‌کنند و قیمت/مبلغ/آدرس پیش‌فرض را خودسرانه اصلاح نمی‌کنند.

برای فایل خصوصی، ابتدا backup و dry-run فرمان انتقال، سپس apply و تأیید SHA256؛ purge نسخهٔ عمومی فقط بعد از تأیید کامل انجام شود. این عملیات روی دادهٔ واقعی هنوز اجرا نشده است. تغییر storage در migration به‌تنهایی فایل‌های قدیمی را جابه‌جا نمی‌کند. asset QR قدیمی نیز فقط با backfill صریح ایجاد می‌شود.

راه‌اندازی API/worker باید هماهنگ باشد: JWTهای بدون epoch و challengeهای قدیمی MFA پس از rollout معتبر نیستند. `AUTH_TRUSTED_PROXY_NETWORKS` باید فقط peerهای واقعی را شامل شود؛ outer proxy باید `X-Mallbyte-Client-IP` را بازنویسی کند. تعرفهٔ `CHECKOUT_SHIPPING_COST` از سرور و پیش‌فرض آن صفر است؛ TTL رزرو پیش‌فرض۱۸۰۰ثانیه و Beat cleanup دقیقه‌ای است. installer audit مالی و recovery پنج‌دقیقه‌ای نیازمند فعال‌سازی/پایش آگاهانه است. مجوز جدید restock باید فقط پس از بازبینی نقش‌ها واگذار شود.

rollback schema یا کد، StockMovement ثبت‌شده یا پول/فایل جابه‌جاشده را خودکار برنمی‌گرداند. برای restock، audit و کلیدهای تکرار باید حفظ شوند؛ اصلاح forward و حرکت جبرانی بازبینی‌شده از پاک‌کردن تاریخچه امن‌تر است.

## موارد باقی‌مانده و اولویت بعدی

| اولویت | کار دقیق | وضعیت/شرط تکمیل |
|---|---|---|
| P0 | review و merge تغییرات امنیت/یکپارچگی با رعایت parent و CI نهایی | کد در PRها آماده؛ merge به تأیید کاربر واگذار شده |
| P1 | reconciliation موجودی و Review تاریخی در محیط واقعی | رفتار مخرب migration تأیید شده؛ داده/backup واقعی بررسی نشده؛ امکان بازسازی بدون منبع قابل اعتماد قابل ادعا نیست |
| P1 | migration/file rollout و grant صریح نقش‌ها و پایش expiry/audit در staging | اجرای واقعی هنوز انجام نشده؛ هیچ دادهٔ production تغییر نکرده |
| P2 | drill staging: چند worker، قطع Redis/worker/Beat، TLS/proxy، تحویل ایمیل، load و RTO/RPO/alert | آزمون محلی بخشی را پوشش می‌دهد؛ گیت محیط واقعی باز است |
| P3 | review قراردادهای OpenAPI و CI head نهایی | کد و آزمون در #49 تکمیل؛ runtime/MFA دست‌نخورده و بررسی merge باقی است |
| P3 | artifact پایدار CI و تعیین سیاست reproducibility وابستگی‌های transitive | نیاز نگهداشت؛ vulnerability تأییدشدهٔ باز گزارش نشده |

پنجرهٔ مرجوعی، split-warehouse fulfillment، checkout اختصاصی variant، paid-order cancellation، replacement/repair/store-credit و refund shipping/tax نیازهای محصول جداگانه‌اند. این گزارش نبود سیاست تصویب‌نشده را با نقص امنیتی تأییدشده یکی نمی‌گیرد. سیاست صریح بازگردانی موجودی که کاربر تعیین کرده، در PR48 پیاده شده است؛ قرنطینهٔ خودکار یا افزایش موجودی به‌محض refund اضافه نشده است.

تغییرات سازگاری client مستند شده‌اند: ثبت‌نام `verification_required` به‌جای token فوری، تغییر ایمیل پس از اثبات مقصد، pagination با `results` در endpointهای اصلاح‌شده، headerهای Link/X-Total-Count و endpoint پیام‌های تاریخچه، دانلود خصوصیِ authenticated، کلید checkout/تاریخ انقضا، و upload/tracking/restock مرجوعی. هیچ فایل frontend تغییر نکرده است.

## ترتیب امن merge

از **merge commit** برای حفظ ancestry پشته‌ها استفاده شود. ابتدا parent در main ادغام شود، سپس child به main retarget و CI مجدداً اجرا شود. child نباید در branch parent merge شود. اگر squash/rebase لازم شد، پیش از ادامه باید dependencyها بدون حذف کار و بدون force-push دوباره طراحی شوند.

زنجیره‌های الزامی:

- #19 → #26 → #29 → #33 → #39 → #44 → #45 → #50؛ و #26 → #43، #29 → #40، #33 → #36/#41/#46.
- #17 → #32.
- #25 → #37 → #48 → #28؛ و #25 → #34.
- #27 → #35 → #47؛ و #35 → #31.
- #24 → #38 → #42/#49؛ PR49 پس از همهٔ PRهای runtime از جمله #50 merge شود.
- #18، #20، #21، #22، #23 و #30 مستقل از این زنجیره‌ها و بر پایهٔ main هستند.

یک ترتیب خطی معتبر برای بازبینی و merge پس از سبز شدن CI: **۱۹،۲۶،۲۹،۳۳،۳۹،۴۳،۱۷،۳۲،۲۵،۳۷،۴۸،۲۸،۲۰،۲۲،۴۱،۳۶،۳۰،۲۷،۳۵،۴۷،۳۱،۴۴،۴۵،۵۰،۴۰،۴۶،۳۴،۲۱،۱۸،۲۳،۲۴،۳۸،۴۲،۴۹**. مستقل‌ها را می‌توان زودتر بررسی کرد، اما parent هیچ کودک نباید عقب بماند. merge هر PR باید تعارض احتمالی با main جدید را دوباره بررسی کند؛ نتیجهٔ ترکیبی محلی جایگزین CI پس از merge نیست.

## پاسخ به کامل بودن کدنویسی بک‌اند

**در این checkpoint اعلام «کاملاً تمام و آمادهٔ production» صحیح نیست.** اصلاحات runtime تأییدشده در PRهای باز پیاده و با رگرسیون ترکیبی بررسی شده‌اند؛ اصلاح P1 لغو Shipment بدون بازنویسی state نهایی سفارش و metadata/قرارداد OpenAPI نیز در PR50 و PR49 تکمیل شده‌اند. نقص تأییدشدهٔ کدی دیگری در دامنهٔ بررسی فعلی باز نمانده است؛ نتیجهٔ اجرای نهایی و review PRها باید حفظ شود. در ادامه review/merge، reconciliation تاریخی مبتنی بر backup و rollout/staging gates لازم‌اند. نبود درگاه خارجی مانع این ارزیابی نیست. تا بسته‌شدن این موارد، وضعیت مناسب «آمادهٔ تست دستی و staging کنترل‌شده پس از merge و preflight»، و وضعیت production «تأییدنشده» است.
