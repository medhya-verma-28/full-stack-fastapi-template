import inspect
import json
import re
import sys
import uuid
import random
from datetime import datetime, timezone
from pathlib import Path
from app.api.main import api_router
from typing import Annotated, get_origin, get_args
from fastapi.params import Depends, Security, Query
import importlib.util
from fastapi.security import OAuth2PasswordRequestForm
import os

# Setup project root and append to sys.path to allow internal imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

API_DIR = PROJECT_ROOT / "backend" / "app" / "api"
BACKEND_DIR = PROJECT_ROOT / "backend" / "app" / "api" / "routes"
OUTPUT_DIR = PROJECT_ROOT / "specmatic-test-requests"
OUTPUT_DIR.mkdir(exist_ok=True)

SEEDED_USER_IDS = [
    "a6d59969-aa8a-4911-8b4f-d773905900e3", "8b266026-b682-4fc6-a149-2ba54ee7048d",
    "5630f2d8-456b-46cf-af5a-e7592666e614", "bc53fe2a-83f4-4195-b5ee-9491ea409489",
    "8b76dd7a-3c91-4914-83f5-6a855868ad8d", "1fc5f839-9fa3-4889-880f-d1b12dc4be99",
    "c3930421-73b9-49ad-ad1d-5edb402acffb", "7cc87c47-f9f8-4f4a-ac69-e848af633bb6",
    "83f1e936-f967-469e-80e3-d1d012bf73c3", "070acdde-c2c2-45ae-b1ef-ac4d419fb244",
    "2346f301-56bb-4c66-bf46-4bf9871d2213", "617bbf66-9f1b-4ff3-95ec-8ba2019fdeb9",
    "7aec7153-e6eb-45d0-8b67-ba4bb0a73f65", "0196e188-50a7-441a-9ab5-97878ddcbe6b",
    "ac150939-4fcb-4832-b03c-4f32de6fe3ab", "03dcc788-0422-4911-a21d-008f1b862160",
    "f4b50c25-1cbf-4aba-8a67-d1c061a36927", "f8486f47-2908-4a5e-82be-9a15c913927c",
    "ec94c87d-8a59-4743-aec8-f3b5c1b4c1dc", "f975ada3-8f16-441b-a04e-abe3189fa9db",
    "694b754f-b594-422d-8358-8cdbcfb17d36", "1218319c-53b2-48e3-a48b-af44f96e2749"
]

SEEDED_EMAILS = [
    "admin@example.com", "private.seed@example.com", "signup.user@example.com",
    "unique.user.999@example.com", "medhya999@example.com", "alienated1234455@example.com"
]

mock_generators = {

        # String fields
        "title": f"Test Item {random.randint(1, 1000)}",

        "description":random.choice([
            "Sample description for testing",
            "Mock item description"
        ]),

        "message":random.choice([
            "Operation successful",
            "Request completed successfully",
            "Test message"
        ]),

        # Authentication fields
        "token":str(uuid.uuid4()),

        "access_token": "{{OAUTH2_BEARER_TOKEN}}",

        "token_type":"bearer",

        "sub":random.choice([
            str(uuid.uuid4())
        ]),

        "password":
            f"Password@{random.randint(1000,9999)}"
        ,

        "current_password":
            f"OldPassword@{random.randint(1000,9999)}"
        ,

        "new_password":
            f"NewPassword@{random.randint(1000,9999)}"
        ,

        "hashed_password":
            f"$2b$12${uuid.uuid4().hex}"
        ,

        # User fields
        "user_id": str(uuid.uuid4()),

        "email":random.choice([
            f"user{random.randint(1,10000)}@example.com",
            random.choice(SEEDED_EMAILS)]),

        "private_email": f"user{random.randint(1,10000)}@example.com",

        "full_name":random.choice([
            "John Doe",
            "Alice Smith",
            "Robert Johnson"
        ]),

        "is_active":random.choice([
            True,
            False
        ]),

        "is_superuser":random.choice([
            True,
            False
        ]),

        # UUID fields
        "id":random.choice ([str(uuid.uuid4()),
            random.choice(SEEDED_USER_IDS)]),

        "owner_id":random.choice ([str(uuid.uuid4()),
            random.choice(SEEDED_USER_IDS)]) ,


        # Date fields
        "created_at":
            datetime.now(timezone.utc)
            .isoformat()
        ,

        # Integer fields
        "count":random.randint(1, 20),

        "item_in": {
        "title": f"Test Item {random.randint(1,1000)}",
        "description": random.choice([
            "Sample description for testing",
            "Mock item description"
        ])
    },

    # UserCreate/UserRegister parameter
    "user_in": {
        "email": random.choice([
            f"user{random.randint(1,10000)}@example.com",
            random.choice(SEEDED_EMAILS)
        ]),
        "password": f"Password@{random.randint(1000,9999)}",
        "full_name": random.choice([
            "John Doe",
            "Alice Smith",
            "Robert Johnson"
        ])
    },

    # Generic request body (ResetPassword, etc.)
    "reset_password_body": {
        "token":str(uuid.uuid4()),
        "new_password": f"NewPassword@{random.randint(1000,9999)}"
    },

    "users_me_password_body": {
        "token":str(uuid.uuid4()),
        "current_password":
            f"OldPassword@{random.randint(1000,9999)}"
        ,
        "new_password": f"NewPassword@{random.randint(1000,9999)}"
    },

    # EmailStr parameter
    "email_to": random.choice(SEEDED_EMAILS)}

def generate_mock_data(property_name: str):
    """
    Generate random mock values for FastAPI Pydantic schema properties.
    The returned values can be used directly while creating model instances.
    """
    
    if property_name in mock_generators:
        return mock_generators[property_name]

    defaults = {
        "page": 1,
        "skip": 0,
        "limit": 100,
        "offset": 0,
        "q": "test",
    }
    return defaults.get(property_name, f"mock_{property_name}")
    
def is_injectable(param) -> bool:
    """
    Returns True if a function parameter is a FastAPI dependency
    declared with Annotated[..., Depends(...)] or Security(...).
    """

    annotation = param.annotation

    if annotation == OAuth2PasswordRequestForm:
        return True

    if get_origin(annotation) is Annotated:
        metadata = get_args(annotation)[1:]
        return any(
            isinstance(item, (Depends, Security))
            for item in metadata
        )

    return isinstance(param.default, (Depends, Security))

def get_routes_for_router(main_router, target_prefix: str):
    """
    Recursively scans a main router to find all endpoint route objects 
    belonging to a sub-router matching a specific prefix (e.g., "/items").
    """
    matched_routes = []
    
    # Normalize the target prefix to strip accidental outer slashes
    target_clean = f"/{target_prefix.strip('/')}"
    
    for route in main_router.routes:
        # Check if the route is a sub-router container
        if hasattr(route, "routes"):
            # Check if this sub-router prefix matches what we are searching for
            current_prefix = f"/{getattr(route, 'prefix', '').strip('/')}"
            
            if current_prefix == target_clean:
                # Found the target router! Flatten all its underlying endpoints
                def flatten(routes_list):
                    flat = []
                    for r in routes_list:
                        if hasattr(r, "routes"):
                            flat.extend(flatten(r.routes))
                        else:
                            flat.append(r)
                    return flat
                
                matched_routes.extend(flatten(route.routes))
                break # Stop searching if the unique sub-router is located
                
            else:
                # If prefix doesn't match directly, check if it's nested deeper
                matched_routes.extend(get_routes_for_router(route, target_prefix))
                
    return matched_routes
    
if BACKEND_DIR.exists():
    global_route_prefixes = dict()
    for py_file in BACKEND_DIR.rglob("*.py"):
        if py_file.stem not in ["actuator","__init__"]:
            module_name = py_file.stem
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            module = importlib.util.module_from_spec(spec)

            # 3. Add to sys.modules and execute it
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 4. Safely extract the router instance using getattr
            current_router = getattr(module, "router", None)
            prefix = current_router.prefix or None
            target_endpoints = [route for route in current_router.routes]

            for route in target_endpoints:
                method = next(iter(route.methods))
                endpoint_func = getattr(route, "endpoint", None)
                
                if endpoint_func:
                    endpoint_signature = inspect.signature(endpoint_func)
                    
                    param_vars = []
                    param_types = []

                    for param in endpoint_signature.parameters.values():
                        param_vars.append(param.name)

                        annotation = param.annotation

                        if get_origin(annotation) is Annotated:
                            annotation = get_args(annotation)[0]

                        type_name = getattr(annotation, "__name__", None)

                        if type_name is None:
                            type_name = str(annotation).split(".")[-1]

                        param_types.append(type_name)
                    injectable_types = [
                        name for name, param in endpoint_signature.parameters.items()
                        if is_injectable(param)
                    ]
                    
                    route_path = route.path

                    path_match = re.search(r"{([^{}]+)}", route.path)
                    path_var = path_match.group(1) if path_match else None

                    if path_var:
                        value = generate_mock_data(path_var)
                        if value is None:
                            value = 1

                        route_path = route_path.replace(f"{{{path_var}}}", str(value))

                    # route.path already includes the router prefix
                    api_path = f"/api/v1{route_path}"

                    if api_path.endswith("/reset-password"):
                        api_path += "/"


                    is_form_data = False
                    is_query = False
                    for name, param in endpoint_signature.parameters.items(): 
                        # Unpack inner classes inside Annotated[Type, Dependency] structures 
                        inner_types = get_args(param.annotation) 
                        
                        if param.annotation == OAuth2PasswordRequestForm or OAuth2PasswordRequestForm in inner_types: 
                            is_form_data = True 
                            continue 

                    if is_form_data:
                        param_values = "username=admin%40example.com&password=changethis"
                    elif "test-email" in api_path:
                        api_path += "?email_to=admin%40example.com"

                    else:
                        param_values = dict()
                        for name, param in endpoint_signature.parameters.items():

                            if is_injectable(param):
                                continue

                            if path_var and name == path_var:
                                continue

                            if (name in mock_generators) and method in {"POST", "PUT", "PATCH"}:
                                if name in ["item_in", "user_in", "body"]:
                                    mock_data = generate_mock_data(name)
                                    for k in mock_data:
                                        param_values[k] = mock_data[k]
                                elif "reset-password" in api_path:
                                    param_values["body"] = generate_mock_data("reset_password_body")
                                elif "users/me/password" in api_path:
                                    param_values["body"] = generate_mock_data("users_me_password_body")
                                elif "private" in api_path:
                                    param_values["body"] = generate_mock_data("private_email")
                                else:
                                    param_values[name] = generate_mock_data(name)
                    
                    headers = dict()
                    safe_filename = api_path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
                    output_file = f"{OUTPUT_DIR}/{safe_filename}.json"
                    output_file_name = f"{safe_filename}.json"

                    if is_form_data:
                        headers["Content-Type"] =  "application/x-www-form-urlencoded"
                        headers["Accept"] =  "application/json"
                        http_request_container = {"path": api_path, "method": method, "headers": headers, "body":param_values}
                        output_file = f"{OUTPUT_DIR}/00_{safe_filename}.json"
                        output_file_name = f"00_{safe_filename}.json"
                    elif "test-email" in api_path:
                        headers["Accept"] =  "application/json"
                        headers["Authorization"] =  "Bearer {{OAUTH2_BEARER_TOKEN}}"
                        http_request_container = {"path": api_path, "method": method, "headers": headers}
                        safe_filename = api_path.split("?")[0].strip("/").replace("/", "_").replace("{", "").replace("}", "")
                        output_file = f"{OUTPUT_DIR}/{safe_filename}.json"
                        output_file_name = f"{safe_filename}.json"
                    else:
                        headers["Content-Type"] =  "application/json"
                        headers["Accept"] =  "application/json"
                        headers["Authorization"] =  "Bearer {{OAUTH2_BEARER_TOKEN}}"
                        if method not in ["GET", "DELETE"] and ("test-token" not in api_path) and ("password-recovery" not in api_path):
                            http_request_container = {"path": api_path, "method": method, "headers": headers, "body": param_values}
                        elif ("reset-password" in api_path):
                             http_request_container = {"path": api_path, "method": method, "headers": headers, "body": param_values}
                        else:
                            http_request_container = {"path": api_path, "method": method, "headers": headers}
                    stub_structure = {
                        "http-request": http_request_container
                    }

                    with open(output_file, "w", encoding="utf-8") as fp:
                        json.dump(stub_structure, fp, indent=2)
                    print(f"\033[92mSuccess: Context-Aware request {output_file_name} generated inside: specmatic-test-requests\033[0m")