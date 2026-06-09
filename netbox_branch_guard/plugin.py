from netbox.plugins import PluginConfig
from django.conf import settings
from importlib.metadata import version, PackageNotFoundError



class NetboxBranchGuardConfig(PluginConfig):
    name = "netbox_branch_guard"
    verbose_name = "Netbox Branch Guard"
    description = "Guards against writes to the Main branch and enforces branch usage"

    try:
        __version__ = version("netbox-branch-guard")
    except PackageNotFoundError:
        __version__ = "0.0.0"

    author = "KPTheProf"
    base_url = "netbox-branch-guard"
    url = "https://github.com/KPTheProf/netbox_branch_guard"

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
