from django.http import JsonResponse
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
import re
import logging
import fnmatch


logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

LEVEL_PRIORITY = {
    "debug": 10,
    "info": 20,
    "success": 25,
    "warning": 30,
    "error": 40,
}


class NetboxLogger:
    def __init__(self, request=None, enable_logging=True, log_level="debug"):
        self.request = request
        self.enable_logging = enable_logging
        self.log_level = log_level


    def log(self, level, message, display=None):
        log_level = level.lower()

        # Get the minimum and current level priorities
        min_priority = LEVEL_PRIORITY.get(self.log_level, 40)
        current_priority = LEVEL_PRIORITY.get(log_level, 40)

        # --- Logging (always available) ---
        if log_level == "error" or self.enable_logging:
            log_msg = message

            # Always log using the MIN level, not the original log_level
            log_msg_map = {
                    "debug": logger.debug,
                    "info": logger.info,
                    "success": logger.info,              # no native success level
                    "warning": logger.warning,
                    "error": logger.error,
            }

            # Output the log message using the higest log level value
            if (current_priority >= min_priority):
                log_msg_map.get(log_level, logger.error)(log_msg)
            else:
                log_msg_map.get(self.log_level, logger.error)(log_msg)


        # --- UI Messages ---
        if self.request is not None:
            ui_msg = display or message

            # strip off the [BranchGuard.*] string on the display message
            if ui_msg.startswith("[BranchGuard"):
                ui_msg = re.sub(r"^\[BranchGuard[^\]]*\]\s*", "", ui_msg)


            # Always log using the MIN level, not the original log_level
            ui_msg_map = {
                "debug": messages.debug,
                "info": messages.info,
                "success": messages.success,
                "warning": messages.warning,
                "error": messages.error,
            }

            # Output the UI message using the higest log level value
            if (current_priority >= min_priority):
                ui_msg_map.get(log_level, messages.error)(self.request, ui_msg)
            else:
                ui_msg_map.get(self.log_level, messages.error)(self.request, ui_msg)

        return

    # Optional helpers (recommended)
    def debug(self, message, display=None):
        self.log("debug", message, display)

    def info(self, message, display=None):
        self.log("info", message, display)

    def success(self, message, display=None):
        self.log("success", message, display)

    def warning(self, message, display=None):
        self.log("warning", message, display)

    def error(self, message, display=None):
        self.log("error", message, display)



class NetboxBranchGuardMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

        plugin_config = settings.PLUGINS_CONFIG.get(
            "netbox_branch_guard", {}
        )

        self.enabled = plugin_config.get("enabled", True)
        self.api_bypass = plugin_config.get("api_bypass", True)
        self.superuser_bypass = plugin_config.get("superuser_bypass", True)
        self.enforce_ownership = plugin_config.get("enforce_ownership", True)
        self.logging = plugin_config.get("logging", False)
        self.log_level = plugin_config.get("log_level", "warning").lower()
        self.group_branch_map = plugin_config.get("group_branch_map", {})

        valid_levels = {"debug", "info", "success", "warning", "error"}
        self.log_level = self.log_level if self.log_level in valid_levels else "debug"

        log = NetboxLogger(enable_logging=self.logging, log_level=self.log_level)

        # Verify the settings
        log.debug(
            f"[BranchGuard SETTINGS] "
            f"enabled: {self.enabled}, "
            f"api_bypass: {self.api_bypass}, "
            f"superuser_bypass: {self.superuser_bypass}, "
            f"enforce_ownership: {self.enforce_ownership}, "
            f"logging: {self.logging}, "
            f"log_level: {self.log_level}, "
            f"group_branch_map: {self.group_branch_map} "
        )



    def __call__(self, request):

        # Enable logging
        log = NetboxLogger(request, enable_logging=self.logging, log_level=self.log_level)

        # Verify the request data
        log.debug(f"[BranchGuard REQUEST] {request} ")

        try:
            if not self.enabled:
                return self.get_response(request)

            # Only enforce for write operations
            if request.method not in WRITE_METHODS:
                return self.get_response(request)

            # Get the groups that the user is a member of
            if request.user.is_authenticated:
                user_groups = {g.name for g in request.user.groups.all()}
            else:
                user_groups = set()

            log.debug(
                f"[BranchGuard USER] "
                f"User: {hasattr(request, 'user')}, "
                f"Groups: {user_groups}, "
                f"requst.user.is_authenticated: {request.user.is_authenticated}, "
                f"requst.user.is_superuser: {request.user.is_superuser}, "
                f"requst.path: {request.path} "
            )

            # Ensure user exists
            if not hasattr(request, "user") or not request.user.is_authenticated:
                return self.get_response(request)

            # Allow API usage bypass
            if self.api_bypass and request.path.startswith("/api/"):
                return self.get_response(request)

            # Allow superuser bypass
            if self.superuser_bypass and request.user.is_superuser:
                return self.get_response(request)


            # --- Resolve branch ID (API + UI safe) ---
            branch_id = None

            # API header
            branch_id = request.headers.get("X-NetBox-Branch")

            # UI: branch in query (when present)
            branch_param = request.GET.get("branch")

            if branch_param:
                branch_id = branch_param

                # Persist it for later requests
                request.session["active_branch"] = branch_param

            # UI: branch in cookies (when present)
            if not branch_id:
                branch_id = request.COOKIES.get("active_branch")

            # Fallback for UI POST / navigation
            if not branch_id:
                branch_id = request.session.get("active_branch")

            log.debug(
                f"[BranchGuard DEBUG] "
                f"header={request.headers.get('X-NetBox-Branch')}, "
                f"query={request.GET.get('branch')}, "
                f"session={request.session.get('active_branch')}, "
                f"cookies={request.COOKIES.get('active_branch')}, "
                f"branch_id={branch_id} "
            )

            # Still no branch -> this is MAIN
            if not branch_id:
                log.debug(
                    f"[BranchGuard BLOCK] user={request.user} "
                    f"{request.method} {request.path} -> No Branch (UI/API) "
                )

                if request.path.startswith("/api/"):
                    # Block writes to Main by the /api/
                    log.warning(
                        f"[BranchGuard BLOCK] Blocking writes to Main" 
                        "Writes to the Main branch are restricted"
                    )
                else:
                    # Block writes to Main in the UI
                    log.warning(
                        f"[BranchGuard BLOCK] Blocking writes to Main",
                        "Writes to the Main branch are restricted"
                    )

                # Redirect the user back to the previous page
                return redirect(request.META.get("HTTP_REFERER", "/"))


            # Lazy import
            try:
                from netbox_branching.models import Branch

            except Exception as e:
                log.error(f"[BranchGuardi ERROR] Branch import failed: {e}")

                # Redirect the user back to the previous page
                return redirect(request.META.get("HTTP_REFERER", "/"))


            # Validate branch
            try:
                branch = Branch.objects.get(schema_id=branch_id)

            except Branch.DoesNotExist:
                log.error(f"[BranchGuard ERROR] Invalid branch")

                # Redirect the user back to the previous page
                return redirect(request.META.get("HTTP_REFERER", "/"))

            except Exception as e:
                log.error(f"[BranchGuard ERROR] DB error: {e}")

                # Redirect the user back to the previous page
                return redirect(request.META.get("HTTP_REFERER", "/"))


            # Check for allowed branches
            if self.group_branch_map:
                allowed_branch_patterns = []

                for group_pattern, branch_patterns in self.group_branch_map.items():
                    if any(fnmatch.fnmatch(user_group, group_pattern) for user_group in user_groups):
                        allowed_branch_patterns.extend(branch_patterns)

                if not allowed_branch_patterns:
                    log.warning(f"[BranchGuard BLOCK] You are not assigned to a branch group")

                    # Redirect the user back to the previous page
                    return redirect(request.META.get("HTTP_REFERER", "/"))

                if not any(fnmatch.fnmatch(branch.name, pattern) for pattern in allowed_branch_patterns):
                    log.warning(f'[BranchGuard BLOCK] You cannot use branch "{branch.name}"')
                    log.warning(f"[BranchGuard BLOCK] Only: {', '.join('"' + b +'"' for b in allowed_branch_patterns)}")

                    # Redirect the user back to the previous page
                    return redirect(request.META.get("HTTP_REFERER", "/"))


            # Ownership enforcement
            if self.enforce_ownership and branch.owner != request.user:
                log.warning(
                    f"[BranchGuard BLOCK] user={request.user}, "
                    f"branch_owner={branch.owner}, branch={branch_id} -> Not Branch Owner",
                    f"You can only modify a branch you own"
                )

                # Redirect the user back to the previous page
                return redirect(request.META.get("HTTP_REFERER", "/"))

            log.success(
                f"[BranchGuard ALLOW] user={request.user}, "
                f"{request.method}, {request.path}, branch={branch_id}",
                f""
            )


        except Exception as e:
            log.error(f"[BranchGuard ERROR] {e}")

            # Redirect the user back to the previous page
            return redirect(request.META.get("HTTP_REFERER", "/"))


        return self.get_response(request)

