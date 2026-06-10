from netbox.plugins import PluginConfig
from django.conf import settings
from importlib.metadata import version, PackageNotFoundError

try:
    from ._version import __version__
except ImportError:
    _version__ = "0.0.dev0"


class NetboxBranchGuardConfig(PluginConfig):
    name = "netbox_branch_guard"
    verbose_name = "Netbox Branch Guard"
    description = "Guards against writes to the Main branch and enforces branch usage"
    version = __version__
    author = "KPTheProf"
    homepage = "https://github.com/KPTheProf/netbox_branch_guard"
    license = "Apache-2.0"

    base_url = "netbox-branch-guard"

    min_version = "4.6.0"  # or whatever NetBox version you support



    def ready(self):
        middleware_path = "netbox_branch_guard.middleware.NetboxBranchGuardMiddleware"

        if middleware_path in settings.MIDDLEWARE:
            return

        # Find AuthenticationMiddleware
        try:
            index = settings.MIDDLEWARE.index(
                "django.contrib.messages.middleware.MessageMiddleware"
            )
        except ValueError:
            # fallback: append at end
            settings.MIDDLEWARE.append(middleware_path)
            return

        # Insert AFTER auth middleware
        settings.MIDDLEWARE.insert(index + 1, middleware_path)

config = NetboxBranchGuardConfig
