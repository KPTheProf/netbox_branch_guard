from setuptools import setup, find_packages
from pathlib import Path

about = {}
exec((Path(__file__).parent / "netbox_branch_guard" / "_version.py").read_text(), about)

setup(
    name="netbox_branch_guard",
    description="Guards against writes to the Main branch and enforces branch usage",
    version=about["__version__"],
    author="KPTheProf",
    url="https://github.com/KPTheProf/netbox_branch_guard",
    license="Apache License 2.0",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
)

