from netbox.plugins import PluginConfig
from django.conf import settings
from importlib.metadata import version, PackageNotFoundError
from ._version import __version__


class NetboxBranchGuardConfig(PluginConfig):
    name = "netbox_branch_guard"
    verbose_name = "Netbox Branch Guard"
    description = "Guards against writes to the Main branch and enforces branch usage"
    version = __version__
    author = "KPTheProf"
    base_url = "netbox-branch-guard"

    min_version = "4.6.0"  # or whatever NetBox version you support

    # IMPORTANT: this populates the UI fields
    source = "https://github.com/KPTheProf/netbox_branch_guard"
    license = "Apache 2.0"


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
