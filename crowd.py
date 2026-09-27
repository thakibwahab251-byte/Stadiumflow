"""
crowd.py - In-Memory Crowd Management and Flow Logic for StadiumFlow

Manages real-time stadium zones, base wait times, match phase simulations
(pre_match, first_half, half_time, post_match), and intelligent facility
recommendations based on combined walking and waiting times.
"""

import copy
import json
import os
import random
from datetime import datetime

# Walking time matrix (in minutes) between stadium zones
WALKING_TIME_MATRIX = {
    ("North", "North"): 1,
    ("East", "East"): 1,
    ("South", "South"): 1,
    ("North", "East"): 4,
    ("East", "North"): 4,
    ("East", "South"): 4,
    ("South", "East"): 4,
    ("North", "South"): 7,
    ("South", "North"): 7,
}

# Phase multipliers reflecting crowd surge patterns across event stages
PHASE_MULTIPLIERS = {
    "pre_match": {
        "gate": 2.5,
        "food_court": 1.2,
        "restroom": 1.3,
        "help_desk": 1.8,
        "medical_room": 1.0,
    },
    "first_half": {
        "gate": 0.4,
        "food_court": 0.7,
        "restroom": 0.6,
        "help_desk": 0.5,
        "medical_room": 0.8,
    },
    "half_time": {
        # Half-time is the busiest overall period
        "gate": 0.4,
        "food_court": 3.0,
        "restroom": 3.6,
        "help_desk": 1.4,
        "medical_room": 1.2,
    },
    "post_match": {
        "gate": 3.2,
        "food_court": 0.4,
        "restroom": 1.8,
        "help_desk": 1.6,
        "medical_room": 1.0,
    },
}

# Synonyms for user need normalization
NEED_MAPPINGS = {
    "food": "food_court",
    "food court": "food_court",
    "food_court": "food_court",
    "foodcourt": "food_court",
    "snacks": "food_court",
    "drinks": "food_court",
    "beer": "food_court",
    "burger": "food_court",
    "eat": "food_court",
    "concession": "food_court",
    "restroom": "restroom",
    "restrooms": "restroom",
    "toilet": "restroom",
    "toilets": "restroom",
    "washroom": "restroom",
    "bathroom": "restroom",
    "wc": "restroom",
    "gate": "gate",
    "gates": "gate",
    "entry": "gate",
    "exit": "gate",
    "entrance": "gate",
    "turnstile": "gate",
    "help": "help_desk",
    "help desk": "help_desk",
    "help_desk": "help_desk",
    "info": "help_desk",
    "information": "help_desk",
    "support": "help_desk",
    "lost": "help_desk",
    "medical": "medical_room",
    "medical room": "medical_room",
    "medical_room": "medical_room",
    "first aid": "medical_room",
    "first_aid": "medical_room",
    "doctor": "medical_room",
    "paramedic": "medical_room",
    "emergency": "medical_room",
}


def load_venue_data(file_path=None):
    """
    Loads stadium layout and facility records from venue_data.json.

    Args:
        file_path (str, optional): Absolute or relative path to venue_data.json.
            Defaults to the file adjacent to crowd.py.

    Returns:
        dict: Parsed venue data including 'venue', 'zones', and announcements.
    """
    path = file_path or os.path.join(os.path.dirname(__file__), "venue_data.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_walking_time(user_zone, target_zone):
    """
    Computes estimated walking time in minutes between two stadium zones.

    Args:
        user_zone (str): Origin zone (e.g. 'North', 'East', 'South').
        target_zone (str): Destination zone (e.g. 'North', 'East', 'South').

    Returns:
        int: Estimated walking time in minutes.
    """
    u_zone = (user_zone or "North").strip().capitalize()
    t_zone = (target_zone or "North").strip().capitalize()
    return WALKING_TIME_MATRIX.get((u_zone, t_zone), 5)


def simulate_wait_times(phase="half_time", zones=None):
    """
    Simulates facility queue wait times based on event match phases.
    Supported phases: 'pre_match', 'first_half', 'half_time', 'post_match'.
    Note that 'half_time' produces the heaviest surge for food courts and restrooms.

    Args:
        phase (str): The match phase to simulate.
        zones (list, optional): List of zone dictionaries to update.
            If None, loads fresh zones from venue_data.json.

    Returns:
        list: The updated list of zone dictionaries with modified current_wait_time.
    """
    if zones is None:
        data = load_venue_data()
        zones = data.get("zones", [])

    phase_key = phase.lower() if phase and phase.lower() in PHASE_MULTIPLIERS else "half_time"
    multipliers = PHASE_MULTIPLIERS[phase_key]

    for zone in zones:
        z_type = zone.get("type", "food_court")
        base = zone.get("base_wait_time", 4)
        mult = multipliers.get(z_type, 1.0)

        # Compute simulated wait time
        simulated_wait = max(1, round(base * mult))
        zone["current_wait_time"] = simulated_wait
        zone["wait_time_minutes"] = simulated_wait

        # Estimate headcount proportionally
        rate = max(1, zone.get("service_rate_pm", 8))
        zone["current_count"] = int(simulated_wait * rate)

        # Update status threshold
        if simulated_wait >= 14:
            zone["status"] = "critical"
        elif simulated_wait >= 8:
            zone["status"] = "congested"
        elif simulated_wait >= 4:
            zone["status"] = "moderate"
        else:
            zone["status"] = "normal"

    return zones


def best_option(need, user_zone, zones=None, phase="half_time"):
    """
    Finds the optimal facility for an attendee by evaluating the combined
    total of walking time from user_zone plus the current waiting time.

    Args:
        need (str): Attendee requirement (e.g. 'food', 'restroom', 'gate', 'help desk', 'medical room').
        user_zone (str): Current location of user ('North', 'East', or 'South').
        zones (list, optional): Facilities to evaluate. Defaults to loaded venue zones.
        phase (str, optional): Match phase to simulate if zones are fresh. Defaults to 'half_time'.

    Returns:
        dict: Details of the best facility including id, name, zone,
            walking_time, waiting_time, and lowest total_time.
    """
    if zones is None:
        raw_zones = load_venue_data().get("zones", [])
        zones = simulate_wait_times(phase=phase, zones=raw_zones)

    norm_need = (need or "").strip().lower()
    target_type = NEED_MAPPINGS.get(norm_need, norm_need)

    # Filter facilities matching target facility type
    matching = [
        z for z in zones
        if z.get("type") == target_type or target_type in z.get("name", "").lower()
    ]

    # Fallback to all facilities if no direct match
    candidates = matching if matching else zones
    u_zone = (user_zone or "North").strip().capitalize()

    scored = []
    for facility in candidates:
        f_zone = facility.get("zone", "North")
        walk_time = get_walking_time(u_zone, f_zone)
        wait_time = facility.get("current_wait_time", facility.get("wait_time_minutes", facility.get("base_wait_time", 2)))
        total_time = walk_time + wait_time

        scored.append({
            "facility": facility,
            "id": facility.get("id"),
            "name": facility.get("name"),
            "type": facility.get("type"),
            "zone": f_zone,
            "walking_time": walk_time,
            "waiting_time": wait_time,
            "total_time": total_time,
            "recommendation": (
                f"Head to {facility.get('name')} in {f_zone} Zone: "
                f"{walk_time} min walk + {wait_time} min wait = {total_time} min total."
            )
        })

    # Sort by lowest total time, then lowest walking time
    scored.sort(key=lambda item: (item["total_time"], item["walking_time"]))
    return scored[0] if scored else None


class CrowdManager:
    """Manages the in-memory state of stadium zones, wait times, and crowd distribution."""

    def __init__(self, data_path=None):
        """Initializes CrowdManager with venue data and sets baseline halftime simulation."""
        self.data_path = data_path or os.path.join(os.path.dirname(__file__), "venue_data.json")
        self.initial_data = {}
        self.venue = {}
        self.zones = []
        self.announcements = []
        self.current_phase = "half_time"
        self.load_initial_data()

    def load_initial_data(self):
        """Loads baseline stadium layout and zones from venue_data.json."""
        data = load_venue_data(self.data_path)
        self.initial_data = copy.deepcopy(data)
        self.venue = data.get("venue", {})
        self.zones = data.get("zones", [])
        self.announcements = data.get("initial_announcements", [])
        self.current_phase = self.venue.get("event_phase", "half_time")
        simulate_wait_times(phase=self.current_phase, zones=self.zones)

    def set_phase(self, phase):
        """
        Updates the venue match phase and recalculates wait times across all facilities.

        Args:
            phase (str): 'pre_match', 'first_half', 'half_time', or 'post_match'.

        Returns:
            dict: Updated venue summary.
        """
        self.current_phase = phase
        self.venue["event_phase"] = phase
        simulate_wait_times(phase=phase, zones=self.zones)
        return self.get_summary()

    def reset_state(self):
        """Resets the state back to the original venue_data.json baseline."""
        self.venue = copy.deepcopy(self.initial_data.get("venue", {}))
        self.zones = copy.deepcopy(self.initial_data.get("zones", []))
        self.announcements = copy.deepcopy(self.initial_data.get("initial_announcements", []))
        self.current_phase = self.venue.get("event_phase", "half_time")
        simulate_wait_times(phase=self.current_phase, zones=self.zones)
        return self.get_summary()

    def get_summary(self):
        """Calculates global stadium health metrics for executive dashboards."""
        total_in_queues = sum(z.get("current_count", 0) for z in self.zones)
        wait_times = [z.get("current_wait_time", z.get("wait_time_minutes", 0)) for z in self.zones]
        avg_wait = round(sum(wait_times) / max(len(wait_times), 1), 1)

        critical_zones = [z for z in self.zones if z.get("status") in ["critical", "congested"]]
        total_capacity = sum(z.get("capacity", 1) for z in self.zones)
        congestion_index = min(100, int((total_in_queues / max(total_capacity, 1)) * 100))

        return {
            "venue_name": self.venue.get("name", "Stadium"),
            "event_phase": self.current_phase,
            "attendance": f"{self.venue.get('current_attendance', 0):,} / {self.venue.get('total_capacity', 0):,}",
            "congestion_index": congestion_index,
            "avg_wait_minutes": avg_wait,
            "active_chokepoints": len(critical_zones),
            "zones_count": len(self.zones),
            "latest_announcements": self.announcements[:4],
        }

    def get_zones(self):
        """Returns all venue zones with up-to-date queue and wait times."""
        return self.zones

    def get_zone(self, zone_id):
        """
        Finds a single zone by unique ID.

        Args:
            zone_id (str): Unique facility identifier.

        Returns:
            dict or None: Zone data if found.
        """
        for z in self.zones:
            if z.get("id") == zone_id:
                return z
        return None

    def update_zone_from_analysis(self, zone_id, headcount, bottleneck_notes=None):
        """
        Updates zone metrics based on Gemini Vision crowd analysis.
        Recalculates wait time and status automatically.

        Args:
            zone_id (str): Unique identifier of the target facility.
            headcount (int): People count detected by vision AI.
            bottleneck_notes (str, optional): Diagnosis identified by AI.

        Returns:
            dict or None: The updated zone record.
        """
        zone = self.get_zone(zone_id)
        if not zone:
            return None

        zone["current_count"] = max(0, int(headcount))
        rate = max(1, zone.get("service_rate_pm", 10))
        calculated_wait = max(1, round(zone["current_count"] / rate))
        zone["current_wait_time"] = calculated_wait
        zone["wait_time_minutes"] = calculated_wait

        ratio = zone["current_count"] / max(1, zone.get("capacity", 100))
        if ratio >= 0.85 or calculated_wait >= 14:
            zone["status"] = "critical"
        elif ratio >= 0.60 or calculated_wait >= 8:
            zone["status"] = "congested"
        elif ratio >= 0.35:
            zone["status"] = "moderate"
        else:
            zone["status"] = "normal"

        if bottleneck_notes:
            zone["description"] = f"AI Vision: {bottleneck_notes}"

        if zone["status"] in ["critical", "congested"]:
            alt = self.find_optimal_alternative(zone_id)
            alt_text = f" Suggested alternative: {alt['recommended_zone']['name']} ({alt['recommended_zone']['wait_time_minutes']}m wait)." if alt else ""
            self.add_announcement(
                title=f"Crowd Alert: {zone['name']}",
                message=f"Queue has reached {zone['current_count']} people (~{zone['wait_time_minutes']} min wait).{alt_text}",
                urgency="warning" if zone["status"] == "congested" else "danger"
            )

        return zone

    def find_optimal_alternative(self, zone_id):
        """
        Finds the lowest-wait alternative facility of the same type.

        Args:
            zone_id (str): Unique facility identifier.

        Returns:
            dict or None: Alternative routing comparison.
        """
        target = self.get_zone(zone_id)
        if not target:
            return None

        # Delegate to best_option using target's type and zone
        best = best_option(target.get("type"), target.get("zone", "North"), zones=self.zones)
        if not best:
            return None

        recommended = best["facility"]
        if recommended.get("id") == zone_id:
            # If same facility, look for another matching facility
            others = [z for z in self.zones if z.get("type") == target.get("type") and z.get("id") != zone_id]
            if others:
                others.sort(key=lambda z: z.get("current_wait_time", z.get("wait_time_minutes", 99)))
                recommended = others[0]
            else:
                return None

        time_saved = max(0, target.get("wait_time_minutes", 0) - recommended.get("wait_time_minutes", 0))

        return {
            "from_zone": target,
            "recommended_zone": recommended,
            "time_saved_minutes": time_saved,
            "navigation_tip": f"Head towards {recommended.get('zone', 'nearby')} Zone ({recommended.get('section')})."
        }

    def simulate_tick(self):
        """
        Advances the venue crowd state by a subtle time delta (1 simulation tick).
        Models real-world Poisson arrival and service throughput.

        Returns:
            dict: Updated executive summary.
        """
        for zone in self.zones:
            service_rate = max(1, zone.get("service_rate_pm", 10))
            serviced = random.randint(1, max(2, service_rate // 2))
            arrivals = random.randint(0, max(2, service_rate // 2 + 1))

            new_count = zone.get("current_count", 10) - serviced + arrivals
            cap = zone.get("capacity", 150)
            zone["current_count"] = max(2, min(int(cap * 1.15), new_count))

            calculated_wait = max(1, round(zone["current_count"] / service_rate))
            zone["current_wait_time"] = calculated_wait
            zone["wait_time_minutes"] = calculated_wait

            ratio = zone["current_count"] / cap
            if ratio >= 0.85 or calculated_wait >= 14:
                zone["status"] = "critical"
            elif ratio >= 0.60 or calculated_wait >= 8:
                zone["status"] = "congested"
            elif ratio >= 0.35:
                zone["status"] = "moderate"
            else:
                zone["status"] = "normal"

        return self.get_summary()

    def add_announcement(self, title, message, urgency="info"):
        """
        Logs an event advisory to the live stadium dispatch feed.

        Args:
            title (str): Announcement headline.
            message (str): Detailed advisory body.
            urgency (str, optional): 'info', 'warning', or 'danger'.

        Returns:
            dict: The newly created announcement record.
        """
        now_str = datetime.now().strftime("%H:%M")
        ann = {
            "id": f"ann_{len(self.announcements) + 1}_{random.randint(100, 999)}",
            "timestamp": now_str,
            "urgency": urgency,
            "title": title,
            "message": message
        }
        self.announcements.insert(0, ann)
        self.announcements = self.announcements[:20]
        return ann
