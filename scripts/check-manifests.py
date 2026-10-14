#!/usr/bin/env python3
"""Static checks on the rendered manifests (no cluster needed).

    kubectl kustomize k8s/overlays/dev | python3 scripts/check-manifests.py

Catches the mistakes that otherwise only show up as a pod that will not start
(Pod Security rejection) or a connection that silently goes nowhere (a
renamed Service):

  1. every namespaced object is in one of the four trust zones
  2. every workload runs as its own ServiceAccount (not `default`), that
     ServiceAccount exists, and no API token is mounted
  3. every pod satisfies the Pod Security profile its namespace enforces
     (restricted for app/tools, baseline for data/models)
  4. every Service selects at least one workload in its namespace
  5. every `<svc>.<ns>.svc.cluster.local[:port]` found in an env value points
     at a Service (and port) that exists
"""
import re
import sys

import yaml

ZONES = {"app": "restricted", "data": "baseline", "models": "baseline", "tools": "restricted"}
POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}

BASELINE_CAPS = {
    "AUDIT_WRITE", "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL", "MKNOD",
    "NET_BIND_SERVICE", "SETFCAP", "SETGID", "SETPCAP", "SETUID", "SYS_CHROOT",
}
RESTRICTED_VOLUMES = {
    "configMap", "csi", "downwardAPI", "emptyDir", "ephemeral",
    "persistentVolumeClaim", "projected", "secret",
}
FQDN = re.compile(r"([a-z0-9-]+)\.([a-z0-9-]+)\.svc\.cluster\.local(?::(\d+))?")


def pod_spec(doc):
    spec = doc["spec"]
    if doc["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec["template"], spec["template"]["spec"]


def containers(ps):
    for key in ("initContainers", "containers"):
        for c in ps.get(key) or []:
            yield c


def check_pod(label, level, ps, errors):
    pod_sc = ps.get("securityContext") or {}
    if ps.get("hostNetwork") or ps.get("hostPID") or ps.get("hostIPC"):
        errors.append(f"{label}: host namespaces are not allowed")
    for v in ps.get("volumes") or []:
        kinds = set(v) - {"name"}
        if "hostPath" in kinds:
            errors.append(f"{label}: hostPath volume '{v['name']}'")
        if level == "restricted" and not kinds <= RESTRICTED_VOLUMES:
            errors.append(f"{label}: volume '{v['name']}' type {sorted(kinds)} not allowed by restricted")
    for c in containers(ps):
        who = f"{label}/{c['name']}"
        sc = c.get("securityContext") or {}
        caps = sc.get("capabilities") or {}
        added = set(caps.get("add") or [])
        if sc.get("privileged"):
            errors.append(f"{who}: privileged")
        if not added <= BASELINE_CAPS:
            errors.append(f"{who}: capabilities {sorted(added - BASELINE_CAPS)} not allowed by baseline")
        if level != "restricted":
            continue
        if sc.get("allowPrivilegeEscalation") is not False:
            errors.append(f"{who}: allowPrivilegeEscalation must be false")
        if "ALL" not in (caps.get("drop") or []):
            errors.append(f"{who}: must drop ALL capabilities")
        if not added <= {"NET_BIND_SERVICE"}:
            errors.append(f"{who}: restricted only allows adding NET_BIND_SERVICE, got {sorted(added)}")
        non_root = sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot"))
        if non_root is not True:
            errors.append(f"{who}: runAsNonRoot must be true")
        if sc.get("runAsUser", pod_sc.get("runAsUser")) == 0:
            errors.append(f"{who}: runAsUser 0")
        seccomp = (sc.get("seccompProfile") or pod_sc.get("seccompProfile") or {}).get("type")
        if seccomp not in ("RuntimeDefault", "Localhost"):
            errors.append(f"{who}: seccompProfile must be RuntimeDefault or Localhost")


def main():
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    errors = []

    services = {}  # (ns, name) -> (selector, ports)
    service_accounts = set()
    workloads = []  # (ns, kind, name, pod-labels, pod-spec)

    for d in docs:
        kind, meta = d["kind"], d["metadata"]
        ns = meta.get("namespace")
        if kind == "Namespace":
            continue
        if ns not in ZONES:
            errors.append(f"{kind}/{meta['name']}: namespace {ns!r} is not one of {sorted(ZONES)}")
            continue
        if kind == "Service":
            services[(ns, meta["name"])] = (
                d["spec"].get("selector") or {},
                {p["port"] for p in d["spec"]["ports"]},
            )
        elif kind == "ServiceAccount":
            service_accounts.add((ns, meta["name"]))
            if d.get("automountServiceAccountToken") is not False:
                errors.append(f"ServiceAccount {ns}/{meta['name']}: automountServiceAccountToken must be false")
        elif kind in POD_KINDS:
            tmpl, ps = pod_spec(d)
            workloads.append((ns, kind, meta["name"], (tmpl.get("metadata") or {}).get("labels") or {}, ps))

    # 2 + 3: ServiceAccounts and Pod Security
    for ns, kind, name, _labels, ps in workloads:
        label = f"{kind}/{ns}/{name}"
        sa = ps.get("serviceAccountName")
        if not sa or sa == "default":
            errors.append(f"{label}: needs its own serviceAccountName")
        elif (ns, sa) not in service_accounts:
            errors.append(f"{label}: ServiceAccount {sa!r} does not exist in {ns}")
        if ps.get("automountServiceAccountToken") is not False:
            errors.append(f"{label}: automountServiceAccountToken must be false")
        check_pod(label, ZONES[ns], ps, errors)

    # 4: every Service selects something
    for (ns, name), (selector, _ports) in services.items():
        if not selector or not any(
            wns == ns and all(labels.get(k) == v for k, v in selector.items())
            for wns, _k, _n, labels, _ps in workloads
        ):
            errors.append(f"Service {ns}/{name}: selector {selector} matches no workload in the namespace")

    # 5: in-cluster addresses in env values must resolve to a real Service/port
    for ns, kind, name, _labels, ps in workloads:
        for c in containers(ps):
            for env in c.get("env") or []:
                for host_svc, host_ns, port in FQDN.findall(env.get("value") or ""):
                    key = (host_ns, host_svc)
                    where = f"{kind}/{ns}/{name}/{c['name']} env {env['name']}"
                    if key not in services:
                        errors.append(f"{where}: no Service {host_ns}/{host_svc}")
                    elif port and int(port) not in services[key][1]:
                        errors.append(f"{where}: Service {host_ns}/{host_svc} has no port {port}")

    if errors:
        print("Manifest checks FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print(
        f"Manifest checks passed: {len(workloads)} workloads, {len(services)} services, "
        f"{len(service_accounts)} service accounts across {len(ZONES)} namespaces."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
