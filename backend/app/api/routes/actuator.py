from fastapi import APIRouter, Request
from fastapi.routing import APIRoute

router = APIRouter()

@router.get("/actuator/mappings", tags=["actuator"])
async def get_actuator_mappings(request: Request):
    """
    Returns application route mappings in a Spring Boot Actuator format 
    allowing Specmatic to verify backend API test coverage.
    """
    dispatcher_handlers = []
    
    # Safely query routes from the running app instance context
    for route in request.app.routes:
        if isinstance(route, APIRoute):
            # Formulate the array of string methods registered 
            methods = list(route.methods) if route.methods else ["GET"]
            
            for method in methods:
                dispatcher_handlers.append({
                    "handler": f"{route.endpoint.__module__}.{route.endpoint.__name__}",
                    "predicate": f"{{[{route.path}],methods=[{method}]}}"
                })

    return {
        "contexts": {
            "application": {
                "mappings": {
                    "dispatcherHandlers": {
                        "dispatcherServlets": {
                            "dispatcherServlet": dispatcher_handlers 
                        }
                    }
                }
            }
        }
    }


