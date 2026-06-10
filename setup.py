from setuptools import setup, find_packages
from setuptools_scm import get_version

setup(
    name = "netbox_branch_guard",

    use_scm_version={
        "write_to": "netbox_branch_guard/_version.py",
        "fallback_version": "0.0.dev0",
    },

    packages = find_packages(),
    include_package_data = True,
    zip_safe = False,
    install_requires = [],
)

