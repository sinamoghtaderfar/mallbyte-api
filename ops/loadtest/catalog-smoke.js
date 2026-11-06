import http from "k6/http";
import { URL } from "k6/url";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const base = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const parsed = new URL(base);
if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Expected http(s) BASE_URL");
const host = parsed.hostname.toLowerCase();
const safeHosts = ["127.0.0.1", "localhost", "::1"];
if (!safeHosts.includes(host) && !host.includes("staging") && __ENV.ALLOW_EXTERNAL_LOAD !== "I_UNDERSTAND") {
  throw new Error("Non-local/non-staging load tests require ALLOW_EXTERNAL_LOAD=I_UNDERSTAND");
}

const catalogLatency = new Trend("catalog_latency", true);
const catalogFailures = new Rate("catalog_failures");
export const options = {
  vus: Number(__ENV.VUS || 3),
  duration: __ENV.DURATION || "20s",
  thresholds: {
    "http_req_failed": ["rate<0.01"],
    "http_req_duration": ["p(95)<1200"],
    "catalog_failures": ["rate<0.01"],
    "catalog_latency": ["p(95)<1200"],
  },
};

export default function () {
  const health = http.get(`${base}/healthz/`, { tags: { route: "liveness" } });
  check(health, { "health endpoint succeeds": r => r.status === 200 });

  const response = http.get(`${base}/api/products/products/?page=1&page_size=20`, {
    tags: { route: "public_catalog" },
  });
  const ok = check(response, {
    "catalog HTTP 200": r => r.status === 200,
    "catalog has a results list": r => {
      try {
        return Array.isArray(r.json("results"));
      } catch {
        return false;
      }
    },
  });
  catalogFailures.add(!ok);
  catalogLatency.add(response.timings.duration);
  sleep(1);
}
