"""
Affitto Ride & Rent — FastAPI Backend
=====================================
Endpoints:
  POST /api/users          — Create or update user profile
  GET  /api/users/{uid}    — Get user profile
  POST /api/rides          — Book a new ride
  GET  /api/rides/{user_id}— Get ride history for a user
  POST /api/contact        — Submit a rental / contact-us inquiry
"""

import os
import uuid
import json
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
load_dotenv()
# ─── Firebase Admin SDK Initialisation ────────────────────────────────────────
# Path to the service-account key (relative to where uvicorn is launched)
firebase_json = os.getenv("FIREBASE_CREDENTIALS")
# SERVICE_ACCOUNT_PATH = os.path.join(
#     os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
#     "resourcess",
#     "affitto-xxxxxx.json",
# )

if not firebase_json:
    raise Exception("FIREBASE_CREDENTIALS not found")
cred_dict = json.loads(firebase_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
# cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Affitto Ride & Rent API",
    version="1.0.0",
    description="Backend API for the Affitto transport service.",
)

# CORS — allow the frontend (served on any origin during dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    uid: str
    name: str
    email: str
    phone: Optional[str] = ""
    photo_url: Optional[str] = ""


class UserProfileUpdate(BaseModel):
    phone: Optional[str] = None
    name: Optional[str] = None


class RideCreate(BaseModel):
    user_id: str
    pickup: str
    dropoff: str
    distance_km: float = Field(..., gt=0)
    price: float = Field(..., gt=0)


class ContactRequest(BaseModel):
    name: str
    phone: str
    vehicle: str
    message: Optional[str] = ""


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "Affitto Ride & Rent API"}


# ─── User Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/users", status_code=201)
async def create_or_update_user(user: UserProfile):
    """Create a new user profile or update an existing one in Firestore."""
    user_ref = db.collection("users").document(user.uid)
    existing = user_ref.get()

    if existing.exists:
        # Only update fields that are explicitly provided
        update_data = {}
        if user.phone:
            update_data["phone"] = user.phone
        if user.name:
            update_data["name"] = user.name
        if user.photo_url:
            update_data["photo_url"] = user.photo_url
        if update_data:
            update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            user_ref.update(update_data)
        return {"message": "User profile updated", "uid": user.uid}
    else:
        user_ref.set({
            "uid": user.uid,
            "name": user.name,
            "email": user.email,
            "phone": user.phone or "",
            "photo_url": user.photo_url or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"message": "User profile created", "uid": user.uid}


@app.get("/api/users/{uid}")
async def get_user(uid: str):
    """Fetch a user profile from Firestore by UID."""
    user_ref = db.collection("users").document(uid)
    doc = user_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    return doc.to_dict()


@app.patch("/api/users/{uid}")
async def update_user_profile(uid: str, update: UserProfileUpdate):
    """Partially update a user's profile (phone, name)."""
    user_ref = db.collection("users").document(uid)
    doc = user_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {}
    if update.phone is not None:
        update_data["phone"] = update.phone
    if update.name is not None:
        update_data["name"] = update.name
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    user_ref.update(update_data)
    return {"message": "Profile updated", "uid": uid}


# ─── Ride Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/rides", status_code=201)
async def create_ride(ride: RideCreate):
    """Save a new ride booking to Firestore."""
    ride_id = str(uuid.uuid4())
    ride_data = {
        "ride_id": ride_id,
        "user_id": ride.user_id,
        "pickup": ride.pickup,
        "dropoff": ride.dropoff,
        "distance_km": round(ride.distance_km, 2),
        "price": round(ride.price, 2),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("rides").document(ride_id).set(ride_data)
    return {"message": "Ride booked successfully", "ride_id": ride_id, "ride": ride_data}


@app.get("/api/rides/{user_id}")
async def get_rides(user_id: str):
    """Fetch all rides for a given user, most recent first."""
    rides_ref = (
        db.collection("rides")
        .where("user_id", "==", user_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
    )
    docs = rides_ref.stream()
    rides = [doc.to_dict() for doc in docs]
    return {"rides": rides, "count": len(rides)}


# ─── Contact / Rental Inquiry Endpoint ───────────────────────────────────────

@app.post("/api/contact", status_code=201)
async def submit_contact(contact: ContactRequest):
    """Save a rental inquiry / contact-us request to Firestore."""
    request_id = str(uuid.uuid4())
    contact_data = {
        "request_id": request_id,
        "name": contact.name,
        "phone": contact.phone,
        "vehicle": contact.vehicle,
        "message": contact.message or "",
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("contact_requests").document(request_id).set(contact_data)
    return {"message": "Inquiry submitted successfully", "request_id": request_id}
