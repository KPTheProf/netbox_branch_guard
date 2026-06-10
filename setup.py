from setuptools import setup, find_packages
from setuptools_scm import get_version

setup(
    name = "netbox_branch_guard",
    description = "Guards against writes to the Main branch and enforces branch usage",
    version=get_version(root=".", relative_to=__file__),
    author = "KPTheProf",
    url = "https://github.com/KPTheProf/netbox_branch_guard",
    license = "Apache License 2.0",
    packages = find_packages(),
    include_package_data = True,
    zip_safe = False,
    install_requires = [],
)

