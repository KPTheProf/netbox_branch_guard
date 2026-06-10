from setuptools import setup
from setuptools_scm import get_version

setup(
    use_scm_version = {
        "write_to": "netbox_branch_guard/_version.py",
        "fallback_version": "0.0.dev0",
    },

    # This enables pyproject metadata
    py_modules = [],

)

