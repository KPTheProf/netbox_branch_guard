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
    author_url = "https://github.com/KPTheProf/netbox_branch_guard"
    license = "Apache-2.0"

    base_url = "branch-guard"

    min_version = "4.6.0"
    max_version = "4.6.99"

    middleware = (
        "netbox_branch_guard.middleware.NetboxBranchGuardMiddleware",
    )

    default_settings = {
        # plugin is enabled.
        "enabled": True,

        # API can write to Main.
        "api_bypass": True,

        # Superuser can write to Main.
        "superuser_bypass": True,

        # Users can only write to branches they own.
        "enforce_ownership": True,

        # Output detailed logging to the netbox log.
        "logging": False,

        # Valid levels are "debug", "info", "success", "warning", "error"
        "log_level": "debug",

        # Map user groups to their allowed branches
        "group_branch_map": {},
    }



    def ready(self):
        super().ready()

        middleware_path = "netbox_branch_guard.middleware.NetboxBranchGuardMiddleware"

        if middleware_path in settings.MIDDLEWARE:
            return

        ### This middleware needs to be inserted after Auth + Message middleware.
        ###  As Message is already after Auth, then this should suffice.
        # Find MessageMiddleware
        try:
            index = settings.MIDDLEWARE.index(
                "django.contrib.messages.middleware.MessageMiddleware"
            )
        except ValueError:
            # fallback: append at end
            settings.MIDDLEWARE.append(middleware_path)
            return

        # Insert AFTER MessageMiddleware
        settings.MIDDLEWARE.insert(index + 1, middleware_path)

config = NetboxBranchGuardConfig
