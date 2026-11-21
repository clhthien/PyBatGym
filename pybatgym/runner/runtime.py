"""Deployment-owned runtime selection; never accepted from a web form."""
import os


def backend(kind=None):
    kind = kind or os.environ.get('PYBATGYM_RUNTIME', 'docker')
    if kind == 'docker':
        from . import docker_runtime
        return docker_runtime
    if kind == 'podman':
        from . import podman_runtime
        return podman_runtime
    raise ValueError('Unsupported execution runtime')
