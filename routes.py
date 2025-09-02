from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import current_user
from app import app, db
from models import Collection, ApiRequest, Environment, RequestHistory, User
from api_client import ApiClient
from auth import (
    REDIRECT_PATH,
    auth_callback,
    require_login,
    login_route,
    signup_route,
    logout_route,
)
import json


# Authentication routes
@app.route("/login", methods=["GET", "POST"])
def login():
    return login_route()


@app.route("/signup", methods=["GET", "POST"])
def signup():
    return signup_route()


@app.route("/logout")
def logout():
    return logout_route()


@app.route("/landing")
def landing():
    return render_template("landing.html")


# Make session permanent
@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route("/")
def index():
    """Main API testing interface - Landing page for logged out users, home page for logged in"""
    if current_user.is_authenticated:
        # Show authenticated user's data
        collections = Collection.query.filter_by(user_id=current_user.id).all()
        environments = Environment.query.filter_by(user_id=current_user.id).all()
        active_env = Environment.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        return render_template(
            "index.html",
            collections=collections,
            environments=environments,
            active_env=active_env,
        )
    else:
        # Show landing page for anonymous users
        return render_template("landing.html")


@app.route("/collections")
@require_login
def collections():
    """Collections management page"""
    collections = Collection.query.filter_by(user_id=current_user.id).all()
    return render_template("collections.html", collections=collections)


@app.route("/environments")
@require_login
def environments():
    """Environment variables management page"""
    environments = Environment.query.filter_by(user_id=current_user.id).all()
    return render_template("environments.html", environments=environments)


@app.route("/history")
@require_login
def history():
    """Request history page"""
    history = (
        RequestHistory.query.filter_by(user_id=current_user.id)
        .order_by(RequestHistory.timestamp.desc())
        .limit(100)
        .all()
    )
    return render_template("history.html", history=history)


@app.route("/send_request", methods=["POST"])
@require_login
def send_request():
    """Send API request and return response"""
    try:
        # Get form data
        method = request.form.get("method", "GET")
        url = request.form.get("url", "")
        headers_raw = request.form.get("headers", "{}")
        body = request.form.get("body", "")
        body_type = request.form.get("body_type", "json")
        auth_type = request.form.get("auth_type", "")
        auth_data_raw = request.form.get("auth_data", "{}")

        # Parse headers and auth data
        try:
            headers = json.loads(headers_raw) if headers_raw else {}
        except json.JSONDecodeError:
            headers = {}

        try:
            auth_data = json.loads(auth_data_raw) if auth_data_raw else {}
        except json.JSONDecodeError:
            auth_data = {}

        # Get active environment for current user
        active_env = Environment.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        environment_vars = active_env.get_variables() if active_env else {}

        # Send request
        client = ApiClient()
        response_data = client.send_request(
            method=method,
            url=url,
            headers=headers,
            body=body,
            body_type=body_type,
            auth_type=auth_type,
            auth_data=auth_data,
            environment_vars=environment_vars,
        )

        # Save to history
        history_entry = RequestHistory(user_id=current_user.id)
        history_entry.set_request_data(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "body_type": body_type,
                "auth_type": auth_type,
                "auth_data": auth_data,
            }
        )

        if response_data["success"]:
            history_entry.set_response_data(response_data)
            history_entry.status_code = response_data["status_code"]
        else:
            history_entry.set_response_data(
                {"error": response_data.get("error", "Unknown error")}
            )

        history_entry.response_time = response_data.get("response_time", 0)

        db.session.add(history_entry)
        db.session.commit()

        return jsonify(response_data)

    except Exception as e:
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500


@app.route("/save_request", methods=["POST"])
@require_login
def save_request():
    """Save request to collection"""
    try:
        name = request.form.get("name", "Untitled Request")
        method = request.form.get("method", "GET")
        url = request.form.get("url", "")
        headers_raw = request.form.get("headers", "{}")
        body = request.form.get("body", "")
        body_type = request.form.get("body_type", "json")
        auth_type = request.form.get("auth_type", "")
        auth_data_raw = request.form.get("auth_data", "{}")
        collection_id = request.form.get("collection_id")

        # Parse JSON data
        try:
            headers = json.loads(headers_raw) if headers_raw else {}
        except json.JSONDecodeError:
            headers = {}

        try:
            auth_data = json.loads(auth_data_raw) if auth_data_raw else {}
        except json.JSONDecodeError:
            auth_data = {}

        # Verify collection belongs to user if specified
        if collection_id:
            collection = Collection.query.filter_by(
                id=int(collection_id), user_id=current_user.id
            ).first()
            if not collection:
                flash("Collection not found", "error")
                return redirect(url_for("index"))

        # Create new request
        api_request = ApiRequest(
            name=name,
            method=method,
            url=url,
            body=body,
            body_type=body_type,
            auth_type=auth_type,
            collection_id=int(collection_id) if collection_id else None,
        )

        api_request.set_headers(headers)
        api_request.set_auth_data(auth_data)

        db.session.add(api_request)
        db.session.commit()

        flash("Request saved successfully!", "success")
        return redirect(url_for("index"))

    except Exception as e:
        flash(f"Error saving request: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/create_collection", methods=["POST"])
@require_login
def create_collection():
    """Create new collection"""
    name = request.form.get("name", "")
    description = request.form.get("description", "")

    if not name:
        flash("Collection name is required", "error")
        return redirect(url_for("collections"))

    collection = Collection(name=name, description=description, user_id=current_user.id)
    db.session.add(collection)
    db.session.commit()

    flash("Collection created successfully!", "success")
    return redirect(url_for("collections"))


@app.route("/delete_collection/<int:collection_id>", methods=["POST"])
@require_login
def delete_collection(collection_id):
    """Delete collection"""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(collection)
    db.session.commit()

    flash("Collection deleted successfully!", "success")
    return redirect(url_for("collections"))


@app.route("/create_environment", methods=["POST"])
@require_login
def create_environment():
    """Create new environment"""
    name = request.form.get("name", "")
    variables_raw = request.form.get("variables", "{}")

    if not name:
        flash("Environment name is required", "error")
        return redirect(url_for("environments"))

    try:
        variables = json.loads(variables_raw) if variables_raw else {}
    except json.JSONDecodeError:
        flash("Invalid JSON format for variables", "error")
        return redirect(url_for("environments"))

    environment = Environment(name=name, user_id=current_user.id)
    environment.set_variables(variables)

    db.session.add(environment)
    db.session.commit()

    flash("Environment created successfully!", "success")
    return redirect(url_for("environments"))


@app.route("/activate_environment/<int:env_id>", methods=["POST"])
@require_login
def activate_environment(env_id):
    """Activate environment"""
    # Deactivate all user's environments
    Environment.query.filter_by(user_id=current_user.id).update({"is_active": False})

    # Activate selected environment
    environment = Environment.query.filter_by(
        id=env_id, user_id=current_user.id
    ).first_or_404()
    environment.is_active = True

    db.session.commit()

    flash(f'Environment "{environment.name}" activated!', "success")
    return redirect(url_for("environments"))


@app.route("/delete_environment/<int:env_id>", methods=["POST"])
@require_login
def delete_environment(env_id):
    """Delete environment"""
    environment = Environment.query.filter_by(
        id=env_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(environment)
    db.session.commit()

    flash("Environment deleted successfully!", "success")
    return redirect(url_for("environments"))


@app.route("/load_request/<int:request_id>")
@require_login
def load_request(request_id):
    """Load saved request"""
    # Find request in user's collections
    api_request = (
        db.session.query(ApiRequest)
        .join(Collection)
        .filter(ApiRequest.id == request_id, Collection.user_id == current_user.id)
        .first_or_404()
    )
    return jsonify(api_request.to_dict())


@app.route("/export_collection/<int:collection_id>")
@require_login
def export_collection(collection_id):
    """Export collection as JSON"""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=current_user.id
    ).first_or_404()
    return jsonify(collection.to_dict())


@app.route("/import_collection", methods=["POST"])
@require_login
def import_collection():
    """Import collection from Postman JSON"""
    import json
    from sqlalchemy.exc import SQLAlchemyError

    try:
        import_data = request.get_json()
        if not import_data or "info" not in import_data or "item" not in import_data:
            flash("Invalid Postman collection JSON", "error")
            return redirect(url_for("collections"))

        # Create collection
        collection = Collection(
            name=import_data["info"].get("name", "Imported Collection"),
            description=import_data["info"].get("description", ""),
            user_id=current_user.id,
        )
        db.session.add(collection)
        db.session.flush()  # ensures collection.id is available

        def process_items(items, parent_id=None):
            for item in items:
                if "item" in item:
                    # Folder in Postman → recurse
                    process_items(item["item"], parent_id)
                elif "request" in item:
                    req = item["request"]

                    # Extract request data safely
                    method = req.get("method", "GET").upper()
                    url_data = req.get("url", {})
                    url = ""

                    if isinstance(url_data, str):
                        url = url_data
                    elif isinstance(url_data, dict):
                        url = url_data.get("raw") or "/".join(url_data.get("path", []))

                    headers = {
                        h.get("key"): h.get("value")
                        for h in req.get("header", [])
                        if h.get("key")
                    }

                    body_type = "none"
                    body_content = ""
                    if "body" in req:
                        body_type = req["body"].get("mode", "none")
                        if body_type in ("raw", "text"):
                            body_content = req["body"].get("raw", "")
                        elif body_type == "urlencoded":
                            body_content = json.dumps(req["body"].get("urlencoded", []))
                        elif body_type == "formdata":
                            body_content = json.dumps(req["body"].get("formdata", []))
                        elif body_type == "file":
                            body_content = json.dumps(req["body"].get("file", {}))

                    api_request = ApiRequest(
                        name=item.get("name", "Imported Request"),
                        method=method,
                        url=url,
                        body=body_content,
                        body_type=body_type,
                        auth_type=req.get("auth", {}).get("type", "")
                        if isinstance(req.get("auth"), dict)
                        else "",
                        collection_id=collection.id,
                    )

                    api_request.set_headers(headers)
                    if isinstance(req.get("auth"), dict):
                        api_request.set_auth_data(req["auth"])

                    db.session.add(api_request)

        process_items(import_data["item"])

        db.session.commit()
        flash("Postman collection imported successfully!", "success")

    except (SQLAlchemyError, ValueError, KeyError, TypeError) as e:
        db.session.rollback()
        flash(f"Error importing collection: {str(e)}", "error")

    return redirect(url_for("collections"))


@app.route("/clear_history", methods=["POST"])
@require_login
def clear_history():
    """Clear request history"""
    RequestHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("History cleared successfully!", "success")
    return redirect(url_for("history"))


@app.route(REDIRECT_PATH)
def auth_callback_route():
    return auth_callback()
