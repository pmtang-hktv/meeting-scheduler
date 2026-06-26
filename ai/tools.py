TOOLS = [
    {
        "name": "detect_intent",
        "description": "Classify the requester's intent from their message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["schedule_request", "check_availability", "cancel", "reschedule", "mark_day_off", "other"],
                    "description": "The detected intent. Use mark_day_off when the user says they are taking leave / a day off / will be away or on holiday.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
            },
            "required": ["intent", "confidence"],
        },
    },
    {
        "name": "extract_meeting_details",
        "description": "Extract structured meeting details from the conversation so far.",
        "input_schema": {
            "type": "object",
            "properties": {
                "organizer_name": {
                    "type": ["string", "null"],
                    "description": "Full name of the person calling the meeting.",
                },
                "purpose": {
                    "type": ["string", "null"],
                    "description": "Brief description of the meeting purpose.",
                },
                "duration_mins": {
                    "type": ["integer", "null"],
                    "description": "Meeting duration in minutes.",
                },
                "proposed_dt": {
                    "type": ["string", "null"],
                    "description": "Proposed start datetime as ISO8601 with timezone (e.g. 2026-05-10T10:00:00+08:00).",
                },
                "is_external": {
                    "type": "boolean",
                    "description": "True if the meeting involves someone outside HKTV.",
                },
                "location_area": {
                    "type": ["string", "null"],
                    "description": "Rough area/district for external meetings (e.g. 'Causeway Bay', 'Tsim Sha Tsui'). Null for internal.",
                },
                "missing_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of required fields still not collected: organizer_name, purpose, duration_mins, proposed_dt, location_area (external only).",
                },
            },
            "required": ["is_external", "missing_fields"],
        },
    },
    {
        "name": "extract_day_off",
        "description": (
            "Extract the day(s) off for a leave request (use when intent is mark_day_off). "
            "Return ONE entry per distinct day or contiguous range. Treat conjunctions as "
            "SEPARATE entries: 'Tuesday and Thursday' = two entries; 'tomorrow and next Wed' "
            "= two entries. A continuous span like '6-8 Jul' or 'Mon to Wed' = ONE entry with "
            "start and end. Resolve relative dates to the nearest future occurrence, never a "
            "past year."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dates": {
                    "type": "array",
                    "description": "One entry per distinct day or contiguous range the person is off.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "First day of this entry, ISO date YYYY-MM-DD.",
                            },
                            "end_date": {
                                "type": ["string", "null"],
                                "description": "Last day (inclusive) for a range, else null for a single day.",
                            },
                            "half_day": {
                                "type": ["string", "null"],
                                "enum": ["am", "pm", None],
                                "description": (
                                    "'am' for a morning-only half day, 'pm' for an afternoon-only "
                                    "half day, else null for a whole day. Map 'AL (pm)', 'half day "
                                    "in the afternoon', 'leaving early' → 'pm'; 'AL (am)', 'morning "
                                    "off', 'coming in after lunch' → 'am'."
                                ),
                            },
                        },
                        "required": ["start_date"],
                    },
                },
                "person_name": {
                    "type": ["string", "null"],
                    "description": "Name of the person taking leave, if stated.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "detect_vip",
        "description": "Check if the organizer or requester is a VIP.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_vip": {"type": "boolean"},
                "vip_name": {"type": ["string", "null"], "description": "Matched VIP name if is_vip is true."},
            },
            "required": ["is_vip"],
        },
    },
    {
        "name": "detect_urgency",
        "description": "Detect whether the requester has expressed urgency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_urgent": {"type": "boolean"},
                "urgency_signal": {
                    "type": ["string", "null"],
                    "description": "The phrase or word that indicated urgency.",
                },
            },
            "required": ["is_urgent"],
        },
    },
    {
        "name": "detect_external_party",
        "description": "Detect if this is an external party meeting and what type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_external": {"type": "boolean"},
                "party_type": {
                    "type": ["string", "null"],
                    "enum": ["merchant", "business_lunch", "client", "partner", "other_external", None],
                },
            },
            "required": ["is_external"],
        },
    },
    {
        "name": "request_missing_info",
        "description": "Ask the requester for a specific missing field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "missing_field": {
                    "type": "string",
                    "enum": ["organizer_name", "purpose", "duration_mins", "proposed_dt", "location_area"],
                },
                "question": {
                    "type": "string",
                    "description": "Natural language question to ask the requester.",
                },
            },
            "required": ["missing_field", "question"],
        },
    },
    {
        "name": "generate_reply",
        "description": (
            "Generate a reply ONLY when you need to ask the requester for a missing field "
            "or to clarify an ambiguous request. Do NOT use this tool to confirm bookings, "
            "report availability, or say the meeting has been logged — the Python system "
            "handles all of that after you return."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reply": {
                    "type": "string",
                    "description": "The question or clarification to ask the requester.",
                },
                "reply_type": {
                    "type": "string",
                    "enum": [
                        "ask_missing_info",
                        "clarify_ambiguous",
                    ],
                },
            },
            "required": ["reply", "reply_type"],
        },
    },
]
