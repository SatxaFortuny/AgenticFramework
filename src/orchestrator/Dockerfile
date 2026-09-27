FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CHANGED: pre-create the mount points the k8s ConfigMap volumes target
# (see k8s/05-orchestrator.yaml). CRI-O's volume mounter can only bind onto
# directories that already exist in the image - it doesn't auto-create
# multi-level paths like /app/configs/greeting_finance_app on the fly (that's
# the "openat2 ... No such file or directory" CreateContainerError). Creating
# these ahead of time means each ConfigMap volume just mounts over an
# existing empty directory instead of asking the runtime to create one.
#
# `rm -rf /app/configs` first: the repo has a `configs` symlink inside
# src/orchestrator (pointing at ../../configs) so local dev - running
# uvicorn from src/orchestrator - can resolve the same "configs" relative
# path api.py uses. COPY . . brings that symlink into the image as-is; since
# its target doesn't exist inside the container it lands as a dangling
# symlink at /app/configs, and mkdir -p refuses to proceed once something
# non-directory already occupies that path ("File exists"). Clearing it
# first means the ConfigMap-mounted directories replace that dev-only
# symlink rather than colliding with it - the k8s deployment never uses the
# symlink, only local dev does.
#
# NOTE: this list has to be kept in sync with the mountPaths in
# k8s/05-orchestrator.yaml - adding a new app there means adding its
# directory here too. Same manual-duplication rough edge already flagged in
# that manifest (Batch 7 / Helm chart territory to remove it properly).
RUN rm -rf /app/configs && \
    mkdir -p /app/configs/greeting_finance_app/functionalities \
             /app/configs/greeting_finance_app/blueprints

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["python", "api.py"]
