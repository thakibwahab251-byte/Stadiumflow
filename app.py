"""
app.py - Main Flask Application for StadiumFlow

A real-time physical venue experience platform using Google Gemini Vision
for queue estimation, crowd bottleneck detection, and dynamic fan rerouting.
"""

import io
import os
from flask import Flask, jsonify, render_template, request
from crowd import CrowdManager, best_option, simulate_wait_times
from gemini_client import GeminiCrowdClient

# Initialize Flask application
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "stadiumflow-hackathon-2026")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max image upload

# In-memory domain services (no database needed)
crowd_manager = CrowdManager()
gemini_client = GeminiCrowdClient()


@app.route("/")
def index():
    """Renders the main StadiumFlow operational & attendee dashboard."""
    summary = crowd_manager.get_summary()
    zones = crowd_manager.get_zones()
    gemini_status = gemini_client.is_available()
    return render_template(
        "index.html",
        summary=summary,
        zones=zones,
        gemini_ready=gemini_status
    )


@app.route("/api/venue", methods=["GET"])
def api_venue():
    """Returns the venue metadata and aggregate crowd statistics."""
    summary = crowd_manager.get_summary()
    return jsonify({
        "success": True,
        "summary": summary,
        "gemini_connected": gemini_client.is_available(),
        "model": "gemini-3.8-flash"
    })


@app.route("/api/zones", methods=["GET"])
def api_zones():
    """Returns all stadium facilities and their live wait/congestion metrics."""
    return jsonify({
        "success": True,
        "zones": crowd_manager.get_zones()
    })


@app.route("/api/zones/<zone_id>", methods=["GET"])
def api_zone_detail(zone_id):
    """Returns detailed information for a specific stadium zone."""
    zone = crowd_manager.get_zone(zone_id)
    if not zone:
        return jsonify({"success": False, "error": f"Zone '{zone_id}' not found"}), 404

    alt = crowd_manager.find_optimal_alternative(zone_id)
    return jsonify({
        "success": True,
        "zone": zone,
        "alternative": alt
    })


@app.route("/api/best-option", methods=["GET", "POST"])
def api_best_option():
    """
    Finds the optimal facility with lowest walking time + waiting time.
    Accepts 'need' (e.g. food, restroom, gate, help desk, medical room)
    and 'user_zone' (e.g. North, East, South).
    """
    if request.method == "POST":
        data = request.get_json() or {}
        need = data.get("need", "food")
        user_zone = data.get("user_zone", "North")
    else:
        need = request.args.get("need", "food")
        user_zone = request.args.get("user_zone", "North")

    option = best_option(need=need, user_zone=user_zone, zones=crowd_manager.get_zones())
    if not option:
        return jsonify({"success": False, "error": "No matching facility found"}), 404

    return jsonify({
        "success": True,
        "need": need,
        "user_zone": user_zone,
        "best_option": option
    })


@app.route("/api/phase", methods=["POST"])
def api_set_phase():
    """
    Simulates crowd wait times for a specified match phase.
    Supported phases: pre_match, first_half, half_time, post_match.
    """
    data = request.get_json() or {}
    phase = data.get("phase", "half_time")
    summary = crowd_manager.set_phase(phase)
    return jsonify({
        "success": True,
        "phase": phase,
        "summary": summary,
        "zones": crowd_manager.get_zones()
    })


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """
    Answers a fan's question using Gemini 3.8 Flash, strictly grounded in computed venue facts.
    Returns at most 3 sentences, falling back to plain facts if the key is missing or call fails.
    """
    data = request.get_json() or {}
    question = data.get("question", "Where is the shortest wait right now?")
    need = data.get("need", "food")
    user_zone = data.get("user_zone", "North")

    # Compute best option facts
    opt = best_option(need=need, user_zone=user_zone, zones=crowd_manager.get_zones())
    facts = opt.get("recommendation") if opt else "All stadium concourses are operating at normal capacity."

    # Ask Gemini with strict fact grounding
    answer = gemini_client.answer_fan_question(facts=facts, question=question)

    return jsonify({
        "success": True,
        "question": question,
        "facts": facts,
        "answer": answer,
        "best_option": opt
    })


@app.route("/api/analyze-queue", methods=["POST"])
def api_analyze_queue():
    """
    Submits a queue photo or CCTV capture to Gemini Vision for analysis.
    Updates the zone status and provides smart reroute recommendations.
    """
    zone_id = request.form.get("zone_id") or request.json.get("zone_id", "food_north")
    zone = crowd_manager.get_zone(zone_id)

    if not zone:
        return jsonify({"success": False, "error": "Invalid zone specified"}), 400

    image_bytes = None
    mime_type = "image/jpeg"

    # Check for direct file upload
    if "image" in request.files and request.files["image"].filename:
        uploaded_file = request.files["image"]
        mime_type = uploaded_file.content_type or "image/jpeg"
        image_bytes = uploaded_file.read()

    # Or check for pre-bundled demo scenario triggers
    scenario = request.form.get("scenario") or (request.json.get("scenario") if request.is_json else None)
    if not image_bytes and scenario:
        # Generate a lightweight colored synthetic sample image for testing
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (640, 480), color=(20, 28, 48))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 600, 440], outline=(40, 80, 160), width=3)
        draw.text((60, 80), f"STADIUM CCTV FEED - {zone['name'].upper()}", fill=(240, 240, 240))
        draw.text((60, 120), f"Camera ID: CAM-{zone_id.upper()} | Live Concourse Feed", fill=(120, 200, 255))
        
        # Draw mock person silhouettes to give vision AI real subjects
        num_sim_people = 35 if "congested" in scenario else 12
        for i in range(num_sim_people):
            x = 80 + (i % 8) * 65
            y = 180 + (i // 8) * 80
            draw.ellipse([x, y, x + 24, y + 24], fill=(220, 220, 230))  # Head
            draw.rectangle([x - 6, y + 24, x + 30, y + 65], fill=(80, 110, 160))  # Body

        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()
        mime_type = "image/jpeg"

    if not image_bytes:
        return jsonify({"success": False, "error": "No image or scenario provided"}), 400

    # Call Gemini Multimodal Vision
    analysis = gemini_client.analyze_queue_image(
        image_bytes=image_bytes,
        mime_type=mime_type,
        zone_context=zone
    )

    # Apply findings to update live zone state
    headcount = analysis.get("headcount", zone.get("current_count", 50))
    bottleneck = analysis.get("bottleneck_reason", "Identified by Gemini Vision")
    updated_zone = crowd_manager.update_zone_from_analysis(zone_id, headcount, bottleneck)

    # Compute optimal alternative reroute path
    alternative = crowd_manager.find_optimal_alternative(zone_id)

    return jsonify({
        "success": True,
        "zone": updated_zone,
        "analysis": analysis,
        "alternative": alternative,
        "summary": crowd_manager.get_summary()
    })


@app.route("/api/reroute", methods=["POST"])
def api_reroute():
    """Calculates the best low-wait alternative for a designated congested zone."""
    data = request.get_json() or {}
    zone_id = data.get("zone_id")
    if not zone_id:
        return jsonify({"success": False, "error": "zone_id is required"}), 400

    alt = crowd_manager.find_optimal_alternative(zone_id)
    if not alt:
        return jsonify({"success": False, "message": "No alternative zone found of same category"}), 404

    return jsonify({
        "success": True,
        "reroute": alt
    })


@app.route("/api/broadcast", methods=["POST"])
def api_broadcast():
    """Generates an AI crowd diversion advisory and adds it to the stadium feed."""
    data = request.get_json() or {}
    zone_id = data.get("zone_id")
    zone = crowd_manager.get_zone(zone_id) if zone_id else None

    if not zone:
        return jsonify({"success": False, "error": "Zone not found"}), 404

    alt = crowd_manager.find_optimal_alternative(zone_id)
    alt_name = alt["recommended_zone"]["name"] if alt else None
    alt_wait = alt["recommended_zone"]["wait_time_minutes"] if alt else None
    time_saved = alt.get("time_saved_minutes", 0) if alt else 0

    # Generate message using Gemini
    message = gemini_client.generate_advisory(
        zone_name=zone["name"],
        wait_minutes=zone["wait_time_minutes"],
        alt_zone_name=alt_name,
        alt_wait=alt_wait,
        time_saved=time_saved
    )

    urgency = "danger" if zone["status"] == "critical" else "warning"
    announcement = crowd_manager.add_announcement(
        title=f"Crowd Flow Advisory: {zone['name']}",
        message=message,
        urgency=urgency
    )

    return jsonify({
        "success": True,
        "announcement": announcement,
        "feed": crowd_manager.get_summary()["latest_announcements"]
    })


@app.route("/api/simulate-tick", methods=["POST"])
def api_simulate_tick():
    """Advances crowd dynamics by one simulation step to demonstrate a living arena."""
    summary = crowd_manager.simulate_tick()
    return jsonify({
        "success": True,
        "summary": summary,
        "zones": crowd_manager.get_zones()
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Resets all stadium queues and announcements back to initial state."""
    summary = crowd_manager.reset_state()
    return jsonify({
        "success": True,
        "summary": summary,
        "zones": crowd_manager.get_zones()
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() in ["true", "1", "yes"]
    print(f"🏟️  StadiumFlow running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
