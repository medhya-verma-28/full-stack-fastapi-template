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
from fastapi.params import Depends, Security
import importlib.util
from fastapi.security import OAuth2PasswordRequestForm
from tests.utils.utils import random_email, random_lower_string
from app.utils import generate_password_reset_token
# Setup project root and append to sys.path to allow internal imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

API_DIR = PROJECT_ROOT / "backend" / "app" / "api"
BACKEND_DIR = PROJECT_ROOT / "backend" / "app" / "api" / "routes"
OUTPUT_DIR = PROJECT_ROOT / "specmatic-test-requests"
OUTPUT_DIR.mkdir(exist_ok=True)

SEEDED_USER_IDS ='3dcc3432-0289-482a-bae2-46937a2ae78e'

SEEDED_EMAILS = "admin@example.com"

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
        "token": generate_password_reset_token("admin@example.com"),

        "access_token": "Bearer {{OAUTH2_BEARER_TOKEN}}",

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

        "new_password": "changethis"
        ,

        "hashed_password":
            f"$2b$12${uuid.uuid4().hex}"
        ,

        # User fields
        "user_id": random.choice([str(uuid.uuid4()),SEEDED_USER_IDS]),

        "email":random.choice([
            random_email(),
            SEEDED_EMAILS]),

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
            SEEDED_USER_IDS]),

        "owner_id":random.choice ([str(uuid.uuid4()),
            SEEDED_USER_IDS]) ,


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
            random_email(),
            SEEDED_EMAILS
        ]),
        "password": "changethis",
        "full_name": random.choice([
            "John Doe",
            "Alice Smith",
            "Robert Johnson"
        ]),
        "is_verified": random.choice([True, False])
    },

    # Generic request body (ResetPassword, etc.)
    "reset_password_body": {
        "token": generate_password_reset_token("admin@example.com"),
        "new_password": "changethis"
    },

    "users_me_password_body": {
        "token": generate_password_reset_token("admin@example.com"),
        "current_password":
            "changethis"
        ,
        "new_password": "changethis"
    },

    "private_users_body" : {"email": random_lower_string()+random_email(),
      "password": "changethis",
      "full_name": random.choice([
            "John Doe",
            "Alice Smith",
            "Robert Johnson"
        ]),
      "is_verified": random.choice([True, False])},

    # EmailStr parameter
    "email_to": SEEDED_EMAILS,
    # OAuth2 login
"username": "admin@example.com",

# Password recovery
"email": random.choice([SEEDED_EMAILS,random_lower_string()+random_email()]),

# Users
"user_update": {
    "email": random_lower_string()+random_email(),
    "full_name": random.choice([
        "John Doe",
        "Alice Smith",
        "Robert Johnson"
    ]),
    "password": "changethis",
    "is_active": random.choice([True, False]),
    "is_superuser": random.choice([True, False])
},

"user_me_update": {
    "email": "admin@example.com",
    "full_name": random.choice([
        "John Doe",
        "Alice Smith",
        "Robert Johnson"
    ]),
    "password": "changethis",
    "is_active": True,
    "is_superuser": True
},

"user_me_password_update":{
    "current_password": "changethis",
    "new_password": "changethis"
},

# Items (This would fail always in boilerplate setup as no items are defined)
"item_update": {
    "title": f"Updated Item {random.randint(1,1000)}",
    "description": random.choice([
        "Updated description",
        "Updated mock description"
    ])
},

# UUID path parameters
"id": SEEDED_USER_IDS,

# Query params
"skip": random.randint(0,50),
"limit": random.randint(1,100)}

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
                for method in sorted(route.methods):
                    if method in {"HEAD", "OPTIONS"}:
                        continue
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

                                if "private" in api_path:
                                    param_values.update(generate_mock_data("private_users_body"))
                                    continue
                                if "reset-password" in api_path:
                                     reset_password_params = generate_mock_data("reset_password_body")
                                     continue

                                if "users/signup" in api_path:
                                    param_values.update(generate_mock_data("user_in"))
                                    continue

                                if api_path.endswith("/users/") and method == "POST":
                                    param_values.update(generate_mock_data("user_in"))
                                    continue

                                if ("/users/" in api_path) and ("/users/me/password" not in api_path) and ("/users/me" not in api_path) and (method == "PATCH"):
                                    param_values.update(generate_mock_data("user_update"))
                                    continue

                                if ("/users/me" in api_path) and ("/users/me/password" not in api_path) and (method == "PATCH"):
                                    param_values.update(generate_mock_data("user_me_update"))
                                    continue

                                if ("/users/me/password" in api_path) and (method == "PATCH"):
                                    param_values.update(generate_mock_data("user_me_password_update"))
                                    continue

                                if api_path.endswith("/items/") and method == "POST":
                                    param_values.update(generate_mock_data("item_in"))
                                    continue

                                if "/items/" in api_path and method == "PUT":
                                    param_values.update(generate_mock_data("item_update"))
                                    continue

                                if "/items/" in api_path and method == "PATCH":
                                    param_values.update(generate_mock_data("item_update"))
                                    continue

                                if (name in mock_generators) and method in {"POST", "PUT", "PATCH"}:
                                    if name in ["item_in", "user_in", "body"]:
                                        mock_data = generate_mock_data(name)
                                        for k in mock_data:
                                            param_values[k] = mock_data[k]
                                    
                                    else:
                                        param_values[name] = generate_mock_data(name)
                                        continue
                        
                        headers = dict()
                        if (path_var) or "test-email" in api_path:
                            safe_filename = method + "_" +"_".join(api_path.strip("/").replace("/", "_").replace("{", "").replace("}", "").split("_")[:-1]+[api_path.strip("/").replace("/", "_").replace("{", "").replace("}", "").split("_")[-1][:5]])
                        else:
                            safe_filename = method + "_" +api_path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
                        output_file = f"{OUTPUT_DIR}/{safe_filename}.json"
                        output_file_name = f"{safe_filename}.json"

                        if is_form_data:
                            headers["Content-Type"] =  "application/x-www-form-urlencoded"
                            headers["Accept"] =  "application/x-www-form-urlencoded"
                            http_request_container = {"path": api_path, "method": method, "headers": headers, "body":param_values}
                        elif "test-email" in api_path:
                            headers["Accept"] =  "application/json"
                            headers["Authorization"] =  "Bearer {{OAUTH2_BEARER_TOKEN}}"
                            http_request_container = {"path": api_path, "method": method, "headers": headers}
                            safe_filename = method + "_" +api_path.split("?")[0].strip("/").replace("/", "_").replace("{", "").replace("}", "")
                            output_file = f"{OUTPUT_DIR}/{safe_filename}.json"
                            output_file_name = f"{safe_filename}.json"
                        elif "signup" in api_path:
                            headers["Content-Type"] = "application/json"
                            headers["Accept"] = "application/json"

                            http_request_container = {
                                "path": api_path,
                                "method": method,
                                "headers": headers,
                                "body": param_values
                            }
                        elif "password-recovery" in api_path and "password-recovery-html-content" not in api_path:
                            headers["Accept"] = "application/json"
                            headers["Authorization"] =  "Bearer {{OAUTH2_BEARER_TOKEN}}"

                            http_request_container = {
                                "path": api_path,
                                "method": method,
                                "headers": headers
                            }
                        elif "reset-password" in api_path:
                            headers["Content-Type"] = "application/json"
                            headers["Accept"] = "application/json"
                            

                            http_request_container = {
                                "path": api_path,
                                "method": method,
                                "headers": headers,
                                "body": reset_password_params
                            }
                        else:
                            headers["Content-Type"] =  "application/json"
                            headers["Accept"] =  "application/json"
                            headers["Authorization"] =  "Bearer {{OAUTH2_BEARER_TOKEN}}"
                            if method not in ["GET", "DELETE"] and ("test-token" not in api_path):
                                http_request_container = {"path": api_path, "method": method, "headers": headers, "body": param_values}
                            else:
                                http_request_container = {"path": api_path, "method": method, "headers": headers}
                        stub_structure = {
                            "http-request": http_request_container
                        }

                        with open(output_file, "w") as fp:
                            json.dump(stub_structure, fp, indent=2)
                        print(f"\033[92mSuccess: Context-Aware request {output_file_name} generated inside: specmatic-test-requests\033[0m")