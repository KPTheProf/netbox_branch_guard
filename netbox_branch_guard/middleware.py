from django.http import JsonResponse
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve, Resolver404
import re
import logging
import fnmatch
import json
import io
import importlib


logger = logging.getLogger(__name__)


def _is_field_changed(obj, field, submitted_value):
    # Get current value from database object
    attname = getattr(field, 'attname', field.name)
    current_val = getattr(obj, attname, getattr(obj, field.name, None))
    
    # Check if field is m2m or current_val is a relation manager (e.g., tags)
    is_m2m = hasattr(current_val, 'all') or getattr(field, 'many_to_many', False)
    
    if is_m2m:
        if submitted_value is None or submitted_value == "" or submitted_value == []:
            sub_list = []
        elif isinstance(submitted_value, (list, tuple)):
            sub_list = [str(v) for v in submitted_value if v is not None and v != ""]
        else:
            sub_list = [str(submitted_value)]
            
        if hasattr(current_val, 'all'):
            curr_list = [str(pk) for pk in current_val.values_list('pk', flat=True)]
        elif isinstance(current_val, (list, tuple)):
            curr_list = [str(v) for v in current_val if v is not None and v != ""]
        else:
            curr_list = [str(current_val)] if current_val is not None else []
            
        return sorted(sub_list) != sorted(curr_list)

    # If current_val is a relation, get its pk
    if hasattr(current_val, 'pk'):
        current_val = current_val.pk
        
    # Coerce/normalize submitted_value
    # If it's a dict (nested serializer), extract 'id' or 'pk'
    if isinstance(submitted_value, dict):
        submitted_value = submitted_value.get('id', submitted_value.get('pk', submitted_value))
    
    # If it's a list/tuple (e.g. choices or multiselect), normalize it
    if isinstance(submitted_value, (list, tuple)):
        sub_list = sorted([str(v) for v in submitted_value])
        if isinstance(current_val, (list, tuple)):
            curr_list = sorted([str(v) for v in current_val])
        else:
            curr_list = [str(current_val)] if current_val is not None else []
        return sub_list != curr_list

    # Compare string representations to avoid type mismatch issues
    # Also normalize None / empty string / False
    def normalize(v):
        if v is None or v == "" or v is False:
            return ""
        if v is True:
            return "true"
        return str(v).strip().lower()

    return normalize(current_val) != normalize(submitted_value)

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
        if self.request is not None and log_level != "debug":
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
        self.excluded_models = {m.lower() for m in plugin_config.get("excluded_models", [])}
        self.excluded_fields = {f.lower() for f in plugin_config.get("excluded_fields", [])}
        self.view_model_map = plugin_config.get("view_model_map", {})

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
            f"group_branch_map: {self.group_branch_map}, "
            f"excluded_models: {self.excluded_models}, "
            f"excluded_fields: {self.excluded_fields}, "
            f"view_model_map: {self.view_model_map} "
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

                # Check if this write to main is exempt under excluded_models or excluded_fields
                model = None
                resolver_match = None
                block_reasons = []
                try:
                    resolver_match = resolve(request.path_info)
                except Exception as e:
                    block_reasons.append(f"URL resolve failed: {e}")
                    log.warning(f"[BranchGuard BLOCK] URL resolve failed: {e}")

                if resolver_match:
                    view_func = resolver_match.func
                    view_class = getattr(view_func, 'view_class', getattr(view_func, 'cls', None))
                    if view_class:
                        queryset = getattr(view_class, 'queryset', None)
                        if queryset is not None and hasattr(queryset, 'model'):
                            model = queryset.model
                        else:
                            model = getattr(view_class, 'model', None)

                    log.debug(
                        f"[BranchGuard DEBUG] "
                        f"resolver_match={resolver_match}, "
                        f"view_func={view_func}, "
                        f"view_class={view_class}, "
                        f"queryset={queryset}, "
                        f"model={model} "
                    )

                    # Initialize the variables to avoid errors when debugging and the view_model_map isn't defined
                    mapped_model = None
                    module_name = None
                    module = None

                    # If we can't determine the model, then see if there is a mapping in the view_model_map
                    if model is None and view_class:
                        view_name = (
                            f"{view_class.__module__}."
                            f"{view_class.__name__}"
                        )

                        mapped_model = self.view_model_map.get(view_name)

                        if mapped_model:
                            module_name, class_name = mapped_model.rsplit('.', 1)
                            module = importlib.import_module(module_name)
                            model = getattr(module, class_name)

                        log.debug(
                            f"[BranchGuard DEBUG] "
                            f"view_name={view_name}, "
                            f"mapped_model={mapped_model}, "
                            f"module_name={module_name}, "
                            f"module={module}, "
                            f"model={model} "
                        )
                else:
                    block_reasons.append("Could not resolve path to a view")


                # 1. Check if model itself is exempt
                model_exempt = False
                if model:
                    model_label = model._meta.label_lower

                    model_path = (
                        f"{model.__module__}.{model.__name__}"
                    ).lower()

                    log.debug(
                        f"[BranchGuard DEBUG] "
                        f"model_label={model_label}, "
                        f"model_path={model_path} "
                    )

                    if model_label in self.excluded_models or model_path in self.excluded_models or model._meta.app_label == 'netbox_branching':
                        model_exempt = True
                else:
                    block_reasons.append("No model resolved for path")

                if model_exempt:
                    return self.get_response(request)

                # 2. Check if only excluded fields are modified
                fields_exempt = False
                if model:
                    if self.excluded_fields:
                        # Get submitted data
                        submitted_data = {}
                        if request.content_type == "application/json" or request.path_info.startswith("/api/"):
                            try:
                                body = request.body
                                request._body = body
                                request._stream = io.BytesIO(body)
                                submitted_data = json.loads(body)
                            except Exception as e:
                                block_reasons.append(f"JSON body parse failed: {e}")
                                log.warning(f"[BranchGuard BLOCK] JSON body parse failed: {e}")
                        else:
                            submitted_data = request.POST.dict()

                        # Find existing objects being modified
                        pks = []
                        pk = resolver_match.kwargs.get("pk") if resolver_match else None
                        if pk:
                            pks = [pk]
                        else:
                            pk_list = submitted_data.get('pk') or submitted_data.get('id')
                            if pk_list:
                                if isinstance(pk_list, list):
                                    pks = pk_list
                                else:
                                    pks = [pk_list]

                        if pks:
                            try:
                                objs = list(model.objects.filter(pk__in=pks))
                            except Exception as e:
                                block_reasons.append(f"DB fetch failed: {e}")
                                log.warning(f"[BranchGuard BLOCK] DB fetch failed: {e}")
                                objs = []

                            if objs:
                                # Compare changes
                                non_exempt_changes = False
                                
                                # Gather all fields (concrete and m2m)
                                all_fields = {f.name: f for f in model._meta.fields}
                                for m2m in model._meta.many_to_many:
                                    all_fields[m2m.name] = m2m

                                # Check each field in submitted data
                                for field_name, val in submitted_data.items():
                                    if field_name.startswith('cf_'):
                                        cf_name = field_name[3:]
                                        if field_name.lower() in self.excluded_fields or cf_name.lower() in self.excluded_fields or 'custom_fields' in self.excluded_fields:
                                            continue
                                        
                                        for obj in objs:
                                            current_cf_val = obj.custom_fields.get(cf_name) if hasattr(obj, 'custom_fields') and isinstance(obj.custom_fields, dict) else None
                                            
                                            def normalize_cf(v):
                                                if v is None or v == "" or v is False:
                                                    return ""
                                                if v is True:
                                                    return "true"
                                                return str(v).strip().lower()
                                                
                                            if normalize_cf(current_cf_val) != normalize_cf(val):
                                                non_exempt_changes = True
                                                msg = f"Custom field '{cf_name}' changed (old: {current_cf_val}, new: {val})"
                                                block_reasons.append(msg)
                                                break
                                        if non_exempt_changes:
                                            break
                                    else:
                                        field = all_fields.get(field_name)
                                        if not field:
                                            # Might be using attname (e.g. tenant_id instead of tenant)
                                            field = next((f for f in model._meta.fields if f.attname == field_name), None)

                                        if field:
                                            if field_name == 'custom_fields' and isinstance(val, dict):
                                                # Custom fields in API
                                                for obj in objs:
                                                    current_cf = getattr(obj, 'custom_fields', {}) or {}
                                                    if not isinstance(current_cf, dict):
                                                        current_cf = {}
                                                    
                                                    for cf_key, cf_val in val.items():
                                                        if cf_key.lower() in self.excluded_fields or f"cf_{cf_key}".lower() in self.excluded_fields or 'custom_fields' in self.excluded_fields:
                                                            continue
                                                        
                                                        current_cf_val = current_cf.get(cf_key)
                                                        
                                                        def normalize_cf(v):
                                                            if v is None or v == "" or v is False:
                                                                return ""
                                                            if v is True:
                                                                return "true"
                                                            return str(v).strip().lower()
                                                            
                                                        if normalize_cf(current_cf_val) != normalize_cf(cf_val):
                                                            non_exempt_changes = True
                                                            msg = f"Nested custom field '{cf_key}' changed (old: {current_cf_val}, new: {cf_val})"
                                                            block_reasons.append(msg)
                                                            break
                                                    if non_exempt_changes:
                                                        break
                                                if non_exempt_changes:
                                                    break
                                            else:
                                                # Standard database field or Many-to-Many field
                                                if field.name.lower() in self.excluded_fields or getattr(field, 'attname', '').lower() in self.excluded_fields:
                                                    continue
                                                
                                                for obj in objs:
                                                    if _is_field_changed(obj, field, val):
                                                        non_exempt_changes = True
                                                        attname = getattr(field, 'attname', field.name)
                                                        current_val = getattr(obj, attname, getattr(obj, field.name, None))
                                                        if hasattr(current_val, 'pk'):
                                                            current_val = current_val.pk
                                                        msg = f"Field '{field.name}' changed (old: {current_val}, new: {val})"
                                                        block_reasons.append(msg)
                                                        break
                                                if non_exempt_changes:
                                                    break

                                if not non_exempt_changes:
                                    fields_exempt = True
                            else:
                                msg = f"No database objects found for IDs: {pks}"
                                block_reasons.append(msg)
                        else:
                            msg = "No object IDs (pk) found in request (likely a creation request)"
                            block_reasons.append(msg)
                    else:
                        msg = "No excluded fields configured"
                        block_reasons.append(msg)

                if fields_exempt:
                    return self.get_response(request)

                # Format blocking message with reasons
                reason_str = "; ".join(block_reasons) if block_reasons else "restricted write operation"
                display_msg = f"Writes to the Main branch are restricted ({reason_str})"

                if request.path.startswith("/api/"):
                    # Block writes to Main by the /api/
                    log.warning(
                        f"[BranchGuard BLOCK] Blocking writes to Main. Reason: {reason_str}",
                        display_msg
                    )
                else:
                    # Block writes to Main in the UI
                    log.warning(
                        f"[BranchGuard BLOCK] Blocking writes to Main. Reason: {reason_str}",
                        display_msg
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

