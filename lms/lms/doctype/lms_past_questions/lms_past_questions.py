# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

from re import sub

import frappe
from frappe import _
from frappe.model.document import Document


class LMSPastQuestions(Document):
	def validate(self):
		self.validate_payment_app()

	def validate_payment_app(self):
		if self.paid_past_question:
			installed_apps = frappe.get_installed_apps()
			if "payments" not in installed_apps:
				documentation_link = "https://docs.frappe.io/learning/setting-up-payment-gateway"
				frappe.throw(
					_(
						"Please install the 'payments' app to enable this feature. Refer to the documentation: {0}"
					).format(documentation_link)
				)

# create LMS Past Questions
@frappe.whitelist()
def create_past_questions():
	"""
	Create a new LMS Past Question with all related data.
	Handles file uploads, comments, and payment settings.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# Validate required fields
		if not data.get("title"):
			return {"success": False, "error": "Title is required"}

		# Create new Past Question document
		past_question_doc = frappe.new_doc("LMS Past Questions")

		# Set basic fields
		past_question_doc.title = data.get("title", "")
		past_question_doc.description = data.get("description", "")

		# Set educational metadata
		past_question_doc.educational_level = data.get("educational_level", "")
		past_question_doc.subject = data.get("subject", "")
		past_question_doc.question_type = data.get("question_type", "")
		past_question_doc.exam_type = data.get("exam_type", "")
		past_question_doc.academic_year = data.get("academic_year", "")
		past_question_doc.category = data.get("category", "")

		# Set file upload fields
		past_question_doc.file = data.get("file", "")
		past_question_doc.include_answer = 1 if data.get("include_answer", False) else 0

		# Set visibility and status fields
		past_question_doc.enable_comment = 1 if data.get("enable_comment", False) else 0
		past_question_doc.public = 1 if data.get("public", False) else 0
		past_question_doc.drafted = 1 if data.get("drafted", False) else 0
		past_question_doc.student_link = data.get("student_link", "")
		past_question_doc.download_count = 0  # Initialize download count

		# Set payment fields
		past_question_doc.paid_past_question = 1 if data.get("paid_past_question", False) else 0
		if past_question_doc.paid_past_question:
			past_question_doc.amount = data.get("amount", 0)
			past_question_doc.currency = data.get("currency", "")
			past_question_doc.amount_usd = data.get("amount_usd", 0)
		else:
			past_question_doc.amount = 0
			past_question_doc.currency = ""
			past_question_doc.amount_usd = 0

		# Set created_by field
		past_question_doc.created_by = frappe.session.user

		# Insert the past question document
		past_question_doc.insert(ignore_permissions=True)

		# Handle file folder attachments (if provided)
		if data.get("file_folder") and isinstance(data.get("file_folder"), list):
			for file_item in data["file_folder"]:
				if file_item.get("file_url"):
					past_question_doc.append("p_q_file_folder", {
						"files": file_item.get("file_url")
					})

		# Handle comments (if provided)
		if data.get("comments") and isinstance(data.get("comments"), list):
			for comment_item in data["comments"]:
				if comment_item.get("comment"):
					past_question_doc.append("comments", {
						"comment": comment_item.get("comment")
					})

		# Save the document with child tables
		if data.get("file_folder") or data.get("comments"):
			past_question_doc.save(ignore_permissions=True)

		# Commit to database
		frappe.db.commit()

		# Return success response with created document
		return {
			"success": True,
			"message": "Past question created successfully",
			"data": {
				"id": past_question_doc.name,
				"title": past_question_doc.title,
				"description": past_question_doc.description,
				"educational_level": past_question_doc.educational_level,
				"subject": past_question_doc.subject,
				"question_type": past_question_doc.question_type,
				"exam_type": past_question_doc.exam_type,
				"academic_year": past_question_doc.academic_year,
				"category": past_question_doc.category,
				"file_url": past_question_doc.file,
				"include_answer": past_question_doc.include_answer,
				"enable_comment": past_question_doc.enable_comment,
				"public": past_question_doc.public,
				"drafted": past_question_doc.drafted,
				"student_link": past_question_doc.student_link,
				"paid_past_question": past_question_doc.paid_past_question,
				"amount": past_question_doc.amount,
				"currency": past_question_doc.currency,
				"amount_usd": past_question_doc.amount_usd,
				"download_count": past_question_doc.download_count,
				"created_by": past_question_doc.created_by,
			}
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Create Past Question Error")
		return {
			"success": False,
			"error": str(e),
			"traceback": frappe.get_traceback()
		}


@frappe.whitelist()
def update_past_questions():
	"""
	Update an existing LMS Past Question.
	Handles updating all fields, file uploads, comments, and payment settings.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# Validate required fields
		past_question_id = data.get("past_question_id") or data.get("id") or data.get("name")
		if not past_question_id:
			return {"success": False, "error": "past_question_id is required for update"}

		# Check if past question exists
		if not frappe.db.exists("LMS Past Questions", past_question_id):
			return {"success": False, "error": f"Past question {past_question_id} not found"}

		# Get existing past question document
		past_question_doc = frappe.get_doc("LMS Past Questions", past_question_id)

		# Update basic fields (only if provided)
		if "title" in data:
			title = data.get("title", "").strip()
			if not title:
				return {"success": False, "error": "Title cannot be empty"}
			past_question_doc.title = title

		if "description" in data:
			past_question_doc.description = data.get("description", "")

		# Update educational metadata
		if "educational_level" in data:
			past_question_doc.educational_level = data.get("educational_level", "")
		if "subject" in data:
			past_question_doc.subject = data.get("subject", "")
		if "question_type" in data:
			past_question_doc.question_type = data.get("question_type", "")
		if "exam_type" in data:
			past_question_doc.exam_type = data.get("exam_type", "")
		if "academic_year" in data:
			past_question_doc.academic_year = data.get("academic_year", "")
		if "category" in data:
			past_question_doc.category = data.get("category", "")

		# Update file upload fields
		if "file" in data:
			past_question_doc.file = data.get("file", "")
		if "include_answer" in data:
			past_question_doc.include_answer = 1 if data.get("include_answer", False) else 0

		# Update visibility and status fields
		if "enable_comment" in data:
			past_question_doc.enable_comment = 1 if data.get("enable_comment", False) else 0
		if "public" in data:
			past_question_doc.public = 1 if data.get("public", False) else 0
		if "drafted" in data:
			past_question_doc.drafted = 1 if data.get("drafted", False) else 0
		if "student_link" in data:
			past_question_doc.student_link = data.get("student_link", "")

		# Update payment fields
		if "paid_past_question" in data:
			past_question_doc.paid_past_question = 1 if data.get("paid_past_question", False) else 0
			if past_question_doc.paid_past_question:
				if "amount" in data:
					past_question_doc.amount = data.get("amount", 0)
				if "currency" in data:
					past_question_doc.currency = data.get("currency", "")
				if "amount_usd" in data:
					past_question_doc.amount_usd = data.get("amount_usd", 0)
			else:
				past_question_doc.amount = 0
				past_question_doc.currency = ""
				past_question_doc.amount_usd = 0

		# Update file folder attachments (if provided)
		if "file_folder" in data and isinstance(data.get("file_folder"), list):
			# Clear existing file folder entries
			past_question_doc.p_q_file_folder = []
			# Add new entries
			for file_item in data["file_folder"]:
				if file_item.get("file_url"):
					past_question_doc.append("p_q_file_folder", {
						"files": file_item.get("file_url")
					})

		# Update comments (if provided)
		if "comments" in data and isinstance(data.get("comments"), list):
			# Clear existing comments
			past_question_doc.comments = []
			# Add new comments
			for comment_item in data["comments"]:
				if comment_item.get("comment"):
					past_question_doc.append("comments", {
						"comment": comment_item.get("comment")
					})

		# Save the updated document
		past_question_doc.save(ignore_permissions=True)

		# Commit to database
		frappe.db.commit()

		# Return success response with updated document
		return {
			"success": True,
			"message": "Past question updated successfully",
			"data": {
				"id": past_question_doc.name,
				"title": past_question_doc.title,
				"description": past_question_doc.description,
				"educational_level": past_question_doc.educational_level,
				"subject": past_question_doc.subject,
				"question_type": past_question_doc.question_type,
				"exam_type": past_question_doc.exam_type,
				"academic_year": past_question_doc.academic_year,
				"category": past_question_doc.category,
				"file_url": past_question_doc.file,
				"include_answer": past_question_doc.include_answer,
				"enable_comment": past_question_doc.enable_comment,
				"public": past_question_doc.public,
				"drafted": past_question_doc.drafted,
				"student_link": past_question_doc.student_link,
				"paid_past_question": past_question_doc.paid_past_question,
				"amount": past_question_doc.amount,
				"currency": past_question_doc.currency,
				"amount_usd": past_question_doc.amount_usd,
				"download_count": past_question_doc.download_count,
			}
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Update Past Question Error")
		return {
			"success": False,
			"error": str(e),
			"traceback": frappe.get_traceback()
		}


@frappe.whitelist()
def delete_past_questions():
	"""
	Delete an LMS Past Question and all related child records.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# Validate required fields
		past_question_id = data.get("past_question_id") or data.get("id") or data.get("name")
		if not past_question_id:
			return {"success": False, "error": "past_question_id is required for deletion"}

		# Check if past question exists
		if not frappe.db.exists("LMS Past Questions", past_question_id):
			return {"success": False, "error": f"Past question {past_question_id} not found"}

		# Get the document
		past_question_doc = frappe.get_doc("LMS Past Questions", past_question_id)

		# Store the name before deletion
		deleted_name = past_question_doc.name
		deleted_title = past_question_doc.title

		# Delete the document (this will cascade delete child tables)
		past_question_doc.delete(ignore_permissions=True)

		# Commit to database
		frappe.db.commit()

		return {
			"success": True,
			"message": f"Past question '{deleted_title}' deleted successfully",
			"deleted_id": deleted_name
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Delete Past Question Error")
		return {
			"success": False,
			"error": str(e),
			"traceback": frappe.get_traceback()
		}


@frappe.whitelist(allow_guest=True)
def get_tutor_past_questions(tutor):
    """
    Fetch all past questions created by a specific tutor.
    Includes linked data such as subject, category, educational level,
    comments, and attached file folder details.
    """
    try:
        # 1️⃣ Fetch all LMS Past Questions owned by the given tutor
        past_questions = frappe.get_all(
            "LMS Past Questions",
            filters={"owner": tutor},
            fields=[
                "name",
                "title",
                "subject",
                "paid_past_question",
                "amount",
                "file",
                "amount_usd",
                "drafted",
                "public",
                "exam_type",
                "question_type",
                "academic_year",
                "student_link",
                "currency",
                "enable_comment",
                "description",
                "category",
                "educational_level",
                "download_count",
            ],
        )

        # Check if tutor has no past questions
        if not past_questions:
            return {"success": True, "past_questions": []}

        data = []
        for q in past_questions:
            # 2️⃣ Fetch child table: Past Question File Folder
            file_folders = frappe.get_all(
                "Past Question File Folder",
                filters={"parent": q["name"]},
                fields=["files"],
            )

            # 3️⃣ Fetch child table: Past Question Comments
            comments = frappe.get_all(
                "Past Question Comments",
                filters={"parent": q["name"]},
                fields=["comment", "owner", "creation"],
            )

            # 4️⃣ Combine all into a structured JSON object
            data.append({
                "Doctype": "LMS Past Questions",
                "id": q["name"],
                "title": q.get("title"),
                "drafted": q.get("drafted"),
                "public": q.get("public"),
                "exam_type": q.get("exam_type"),
                "question_type": q.get("question_type"),
                "academic_year": q.get("academic_year"),
                "student_link": q.get("student_link"),
                "paid_past_question": q.get("paid_past_question"),
                "amount": q.get("amount"),
                "currency": q.get("currency"),
                "enable_comment": q.get("enable_comment"),
                "amount_usd": q.get("amount_usd"),
                "file_url": q.get("file"),
                "description": q.get("description"),
                "download_count": q.get("download_count") or 0,

                # Linked DocType: LMS Course Level
                "educational_level": (
                    {
                        "id": q.get("educational_level"),
                        "level_name": frappe.db.get_value(
                            "LMS Course Level",
                            q.get("educational_level"),
                            "education_level"
                        ),
                    } if q.get("educational_level") else None
                ),

                # Linked DocType: Subject
                "subject": (
                    {
                        "id": q.get("subject"),
                        "subject_name": frappe.db.get_value(
                            "Subject",
                            q.get("subject"),
                            "subject_name"
                        ),
                    } if q.get("subject") else None
                ),

                # Linked DocType: LMS Category
                "category": (
                    {
                        "id": q.get("category"),
                        "category_name": frappe.db.get_value(
                            "LMS Category",
                            q.get("category"),
                            "category"
                        ),
                    } if q.get("category") else None
                ),

                # ✅ Child Table: File Folder
                "p_q_file_folder": file_folders or [],

                # ✅ Child Table: Comments
                "comments": comments or [],
            })

        # 5️⃣ Return success response
        return {"success": True, "past_questions": data}

    except Exception as e:
        # Log errors for debugging
        frappe.log_error(frappe.get_traceback(), "get_tutor_past_questions Error")
        return {"success": False, "error": str(e)}

@frappe.whitelist(allow_guest=True)
def get_all_categories():
    categories = frappe.get_all("LMS Category", fields=["name", "category"])
    return {"success": True, "categories": categories}


@frappe.whitelist(allow_guest=True)
def get_all_past_questions():
    """
    Fetch all LMS Past Questions with their metadata, including linked subject,
    category, and educational level information. Supports both paid and free questions.
    """
    try:
        # Fetch all records from LMS Past Questions
        past_questions = frappe.get_all(
            "LMS Past Questions",
            fields=[
                "name",
                "title",
                "subject",
                "paid_past_question",
                "amount",
                "file",
                "amount_usd",
                "drafted",
                "public",
                "exam_type",
                "question_type",
                "academic_year",
                "student_link",
                "currency",
                "enable_comment",
                "include_answer",
                "description",
                "category",
                "educational_level",
                "download_count",
            ],
        )

        # Build the response
        data = []
        for q in past_questions:
            # Get child table items for Past Question File Folder
            file_folders = frappe.get_all(
                "Past Question File Folder",
                filters={"parent": q["name"]},
                fields=["files"],
            )

            data.append({
                "Doctype": "LMS Past Questions",
                "id": q["name"],
                "title": q.get("title"),
                "drafted": q.get("drafted"),
                "public": q.get("public"),
                "exam_type": q.get("exam_type"),
                "question_type": q.get("question_type"),
                "academic_year": q.get("academic_year"),
                "student_link": q.get("student_link"),
                "paid_past_question": q.get("paid_past_question"),
                "amount": q.get("amount"),
                "currency": q.get("currency"),
                "enable_comment": q.get("enable_comment"),
                "include_answer": q.get("include_answer"),
                "amount_usd": q.get("amount_usd"),
                "file_url": q.get("file"),
                "description": q.get("description"),
                "download_count": q.get("download_count") or 0,
                "educational_level": (
                    {
                        "id": q.get("educational_level"),
                        "level_name": frappe.db.get_value(
                            "LMS Course Level",
                            q.get("educational_level"),
                            "education_level"
                        ),
                    }
                    if q.get("educational_level") else None
                ),
                "subject": (
                    {
                        "id": q.get("subject"),
                        "subject_name": frappe.db.get_value(
                            "Subject", q.get("subject"), "subject_name"
                        ),
                    }
                    if q.get("subject") else None
                ),
                "category": (
                    {
                        "id": q.get("category"),
                        "category_name": frappe.db.get_value(
                            "LMS Category", q.get("category"), "category"
                        ),
                    }
                    if q.get("category") else None
                ),
                # Correct handling of Table field
                "p_q_file_folder": file_folders or [],
            })

        return {"success": True, "past_questions": data}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_all_past_questions Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_past_question_details(past_question):
    """
    Fetch detailed information about a specific Past Question.
    Includes related subject, category, educational level,
    comments, file folder entries, and bookmark status.
    """
    try:
        past_questions = frappe.get_all(
            "LMS Past Questions",
            filters={"name": past_question},
            fields=[
                "name",
                "title",
                "subject",
                "paid_past_question",
                "amount",
                "file",
                "amount_usd",
                "drafted",
                "public",
                "exam_type",
                "question_type",
                "academic_year",
                "student_link",
                "currency",
                "enable_comment",
                "include_answer",
                "description",
                "category",
                "educational_level",
                "download_count",
            ],
        )

        if not past_questions:
            return {"success": False, "error": "Past question not found"}

        data = []
        session_user = frappe.session.user

        # get the date created and who created it
        uploaded_by = frappe.db.get_value("LMS Past Questions", past_question, "owner")
        date_uploaded = frappe.db.get_value("LMS Past Questions", past_question, "creation")

        # get full details of tutor, not just name
        # tutor = frappe.get_doc("User", uploaded_by, "full_name")
        profile_data = frappe.get_value(
						"User Profile",
						{"user": uploaded_by},
						"*",
						as_dict=True
					)
        
        #Fix spacing issues below
        tutor = []
        if profile_data:
            user_doc = frappe.get_doc("User", profile_data["user"])
            tutor.append({
                "id": profile_data.name,
                "full_name": getattr(user_doc, "full_name", ""),
                "email": getattr(user_doc, "email", ""),
				"phone_number": getattr(profile_data, "phone_number", ""),
				"profile_image_url": getattr(user_doc, "user_image", ""),
				"bio": getattr(profile_data, "bio", ""),
				"rating": getattr(profile_data, "rating", 0),
				"experience_years": getattr(profile_data, "teaching_experience", 0),
				"subjects": json.loads(profile_data.subjects) if getattr(profile_data, "subjects", None) else [],
			})

        for q in past_questions:
            file_folders = frappe.get_all(
                "Past Question File Folder",
                filters={"parent": q["name"]},
                fields=["files"],
            )

            comments = frappe.get_all(
                "Past Question Comments",
                filters={"parent": q["name"]},
                fields=["comment", "owner", "creation"],
            )

            is_bookmarked = False
            if session_user and session_user != "Guest":
                is_bookmarked = frappe.db.exists(
                    "Bookmark",
                    {
                        "reference_name": q["name"],
                        "user": session_user
                    }
                )

            data.append({
                "Doctype": "LMS Past Questions",
                "id": q["name"],
                "title": q.get("title"),
                "drafted": q.get("drafted"),
                "public": q.get("public"),
                "exam_type": q.get("exam_type"),
                "question_type": q.get("question_type"),
                "academic_year": q.get("academic_year"),
                "student_link": q.get("student_link"),
                "paid_past_question": q.get("paid_past_question"),
                "amount": q.get("amount"),
                "currency": q.get("currency"),
                "enable_comment": q.get("enable_comment"),
                "include_answer": q.get("include_answer"),
                "amount_usd": q.get("amount_usd"),
                "file_url": q.get("file"),
                "description": q.get("description"),
                "download_count": q.get("download_count") or 0,
                "is_bookmarked": True if is_bookmarked else False,
                "uploaded_by": tutor,
                "date_uploaded": date_uploaded,

                # Linked DocType: LMS Course Level
                "educational_level": (
                    {
                        "id": q.get("educational_level"),
                        "level_name": frappe.db.get_value(
                            "LMS Course Level", q.get("educational_level"), "education_level"
                        ),
                    } if q.get("educational_level") else None
                ),

                # Linked DocType: Subject
                "subject": (
                    {
                        "id": q.get("subject"),
                        "subject_name": frappe.db.get_value(
                            "Subject", q.get("subject"), "subject_name"
                        ),
                    } if q.get("subject") else None
                ),

                # Linked DocType: LMS Category
                "category": (
                    {
                        "id": q.get("category"),
                        "category_name": frappe.db.get_value(
                            "LMS Category", q.get("category"), "category"
                        ),
                    } if q.get("category") else None
                ),

                "p_q_file_folder": file_folders or [],

                "comments": comments or [],
            })

        return {"success": True, "past_question_details": data}

    except Exception as e:
        # Log full traceback for debugging
        frappe.log_error(frappe.get_traceback(), "get_past_question_details Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_past_question_count_kpi(tutor):
	public_questions = frappe.get_all(
		"LMS Past Questions", filters={"owner": tutor, "public": 1, "drafted": 0}, fields=["student_link"]
	)
	public_questions_count = len(public_questions)

	# Collect all student links (assuming student_link is a user id or similar)
	student_links = [q["student_link"] for q in public_questions if q.get("student_link")]
	unique_students = set(student_links)
	student_demographics_count = len(unique_students)

	return {
		"success": True,
		"published_questions": public_questions_count,
		"student_demographics": student_demographics_count,
		"total_earnings": "GHS 0",
	}

@frappe.whitelist()
def increase_download_count(past_question):
	if not past_question:
		return {"success": False, "message": "Past question ID is required."}

	try:
		pq_doc = frappe.get_doc("LMS Past Questions", past_question)
		pq_doc.download_count = (pq_doc.download_count or 0) + 1
		pq_doc.save(ignore_permissions=True,)
		return {"success": True, "download_count": pq_doc.download_count}
	except Exception as e:
		return {"success": False, "message": str(e)}
