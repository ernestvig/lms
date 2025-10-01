# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from lms.lms.utils import has_course_instructor_role, has_course_moderator_role


class LMSAssignment(Document):
	pass


@frappe.whitelist()
def create_enhanced_assignment():
	"""
	Create an enhanced assignment with proper LMS Question and Quiz Question structure.
	"""
	import json

	from frappe.utils import generate_hash, getdate, now

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# Validate required fields
		required_fields = ["title", "question", "type"]
		for field in required_fields:
			if not data.get(field):
				return {"error": f"Missing required field: {field}"}

		# Parse and validate due date if provided
		due_date = None
		if data.get("due_date"):
			try:
				due_date = getdate(data.get("due_date"))
			except ValueError:
				return {"error": "Invalid due_date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"}

		# Validate assignment type
		valid_types = ["Quiz/Multiple choice", "Practical task", "Video submission", "Essay/Written task"]
		if data.get("type") not in valid_types:
			return {"error": f"Invalid assignment type. Must be one of: {', '.join(valid_types)}"}

		# === Create Assignment using Frappe ORM ===
		assignment_doc = frappe.new_doc("LMS Assignment")

		# Set basic fields
		assignment_doc.title = data.get("title", "")
		assignment_doc.question = data.get("question", "")
		assignment_doc.type = data.get("type", "Essay/Written task")
		assignment_doc.grade_assignment = 1 if data.get("grade_assignment", False) else 0
		assignment_doc.show_answer = 1 if data.get("show_answer", False) else 0
		assignment_doc.answer = data.get("answer", "")
		assignment_doc.instructions = data.get("instructions", "")
		assignment_doc.file = data.get("file", "")
		assignment_doc.resource_link = data.get("resource_link", "")
		assignment_doc.subject = data.get("subject", "")
		assignment_doc.test_score = data.get("test_score", "")
		assignment_doc.status = "Pending"
		assignment_doc.submitted = 0
		assignment_doc.drafted = 1

		if due_date:
			assignment_doc.due_date = due_date

		# === Add Recipients ===
		recipients_created = []
		if "recipient" in data and isinstance(data["recipient"], list):
			for recipient_data in data["recipient"]:
				student_email = recipient_data.get("students")
				if student_email:
					# Check if student exists
					student_exists = frappe.db.exists("User", student_email)
					if not student_exists:
						print(f"Warning: Student {student_email} not found, skipping")
						continue

					# Try different field names for PL Students
					try:
						assignment_doc.append("recipient", {"students": student_email})
						recipients_created.append(student_email)
					except Exception as e:
						try:
							assignment_doc.append("recipient", {"student": student_email})
							recipients_created.append(student_email)
						except ValueError:
							print(f"Could not add recipient {student_email}: {e}")

		# === Create LMS Questions first, then Quiz Questions ===
		lms_questions_created = []
		quiz_questions_created = []

		if (
			data.get("type") == "Quiz/Multiple choice"
			and "quiz_questions" in data
			and isinstance(data["quiz_questions"], list)
		):
			for question_data in data["quiz_questions"]:
				if not question_data.get("question"):
					continue

				# Step 1: Create LMS Question
				lms_question_doc = frappe.new_doc("LMS Question")
				lms_question_doc.question = question_data.get("question", "")
				lms_question_doc.type = "Choices"  # Must be "Choices" for multiple choice
				lms_question_doc.multiple = 0  # Single correct answer

				# Set options using the correct field names
				lms_question_doc.option_1 = question_data.get("option_a", "")
				lms_question_doc.option_2 = question_data.get("option_b", "")
				lms_question_doc.option_3 = question_data.get("option_c", "")
				lms_question_doc.option_4 = question_data.get("option_d", "")

				# Set explanations if provided
				explanation = question_data.get("explanation", "")
				lms_question_doc.explanation_1 = explanation
				lms_question_doc.explanation_2 = explanation
				lms_question_doc.explanation_3 = explanation
				lms_question_doc.explanation_4 = explanation

				# Mark the correct option based on the correct_answer
				correct_answer = question_data.get("correct_answer", "A").upper()

				# Set all to false first
				lms_question_doc.is_correct_1 = 0
				lms_question_doc.is_correct_2 = 0
				lms_question_doc.is_correct_3 = 0
				lms_question_doc.is_correct_4 = 0

				# Mark the correct one
				if correct_answer == "A":
					lms_question_doc.is_correct_1 = 1
				elif correct_answer == "B":
					lms_question_doc.is_correct_2 = 1
				elif correct_answer == "C":
					lms_question_doc.is_correct_3 = 1
				elif correct_answer == "D":
					lms_question_doc.is_correct_4 = 1
				else:
					# Default to option A if invalid
					lms_question_doc.is_correct_1 = 1

				lms_question_doc.insert(ignore_permissions=True)
				lms_questions_created.append(
					{
						"name": lms_question_doc.name,
						"question": question_data.get("question", ""),
						"correct_option": correct_answer,
					}
				)

				# Step 2: Create LMS Quiz Question that links to the LMS Question
				quiz_question_row = {
					"question": lms_question_doc.name,  # Link to LMS Question
					"question_type": question_data.get("question_type", "Multiple Choice"),
					"option_a": question_data.get("option_a", ""),
					"option_b": question_data.get("option_b", ""),
					"option_c": question_data.get("option_c", ""),
					"option_d": question_data.get("option_d", ""),
					"correct_answer": correct_answer,
					"marks": int(question_data.get("marks", 1)),
					"points": int(question_data.get("points", 1)),
					"explanation": question_data.get("explanation", ""),
				}

				assignment_doc.append("quiz_questions", quiz_question_row)
				quiz_questions_created.append(
					{
						"lms_question": lms_question_doc.name,
						"question_text": question_data.get("question", ""),
						"correct_answer": correct_answer,
						"marks": question_data.get("marks", 1),
					}
				)

		# Insert the assignment with quiz questions
		assignment_doc.insert(ignore_permissions=True)
		frappe.db.commit()

		return {
			"success": True,
			"message": "Enhanced assignment created successfully with proper question structure",
			"data": {
				"assignment_name": assignment_doc.name,
				"title": assignment_doc.title,
				"type": assignment_doc.type,
				"due_date": str(assignment_doc.due_date) if assignment_doc.due_date else None,
				"recipients_count": len(recipients_created),
				"lms_questions_count": len(lms_questions_created),
				"quiz_questions_count": len(quiz_questions_created),
				"grade_assignment": bool(assignment_doc.grade_assignment),
				"show_answer": bool(assignment_doc.show_answer),
				"recipients": recipients_created,
				"lms_questions": lms_questions_created,
				"quiz_questions": quiz_questions_created,
				"status": assignment_doc.status,
				"drafted": bool(assignment_doc.drafted),
			},
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Enhanced Assignment Creation Failed")
		return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def add_quiz_questions_to_assignment():
	"""
	Separate method to add quiz questions to an existing assignment.
	Call this after the assignment is created.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		assignment_name = data.get("assignment_name")
		quiz_questions = data.get("quiz_questions", [])

		if not assignment_name:
			return {"error": "assignment_name is required"}

		# Check if assignment exists
		if not frappe.db.exists("LMS Assignment", assignment_name):
			return {"error": "Assignment not found"}

		quiz_questions_created = []

		for question_data in quiz_questions:
			if not question_data.get("question"):
				continue

			# Create using direct SQL to bypass validation issues
			question_name = generate_hash(length=10)
			creation_time = now()

			# Handle correct answer
			correct_answer = question_data.get("correct_answer", "")
			if correct_answer.upper() in ["A", "B", "C", "D"]:
				option_map = {
					"A": question_data.get("option_a", ""),
					"B": question_data.get("option_b", ""),
					"C": question_data.get("option_c", ""),
					"D": question_data.get("option_d", ""),
				}
				correct_answer_text = option_map.get(correct_answer.upper(), correct_answer)
			else:
				correct_answer_text = correct_answer

			# Insert directly into database
			frappe.db.sql(
				"""
                INSERT INTO `tabLMS Quiz Question`
                (name, question, question_type, option_a, option_b, option_c, option_d,
                 correct_answer, marks, points, parent, parenttype, parentfield, idx,
                 creation, modified, modified_by, owner, docstatus)
                VALUES
                (%(name)s, %(question)s, %(question_type)s, %(option_a)s, %(option_b)s,
                 %(option_c)s, %(option_d)s, %(correct_answer)s, %(marks)s, %(points)s,
                 %(parent)s, 'LMS Assignment', 'quiz_questions', %(idx)s, %(creation)s,
                 %(modified)s, %(modified_by)s, %(owner)s, 0)
            """,
				{
					"name": question_name,
					"question": question_data.get("question", ""),
					"question_type": question_data.get("question_type", "Multiple Choice"),
					"option_a": question_data.get("option_a", ""),
					"option_b": question_data.get("option_b", ""),
					"option_c": question_data.get("option_c", ""),
					"option_d": question_data.get("option_d", ""),
					"correct_answer": correct_answer_text,
					"marks": int(question_data.get("marks", 1)),
					"points": int(question_data.get("points", 1)),
					"parent": assignment_name,
					"idx": len(quiz_questions_created) + 1,
					"creation": creation_time,
					"modified": creation_time,
					"modified_by": frappe.session.user,
					"owner": frappe.session.user,
				},
			)

			quiz_questions_created.append(
				{
					"name": question_name,
					"question": question_data.get("question", ""),
					"correct_answer": correct_answer_text,
				}
			)

		frappe.db.commit()

		return {
			"success": True,
			"message": f"Added {len(quiz_questions_created)} quiz questions to assignment",
			"quiz_questions": quiz_questions_created,
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Add Quiz Questions Failed")
		return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_enhanced_assignment_detail(assignment_name):
	"""
	Fetch assignment details with recipients and quiz questions
	"""
	try:
		# Get assignment basic info
		assignment_data = frappe.db.sql(
			"""
            SELECT name, title, company, question, type, grade_assignment, file,
                   resource_links, show_answer, answer, due_date, creation, owner
            FROM `tabLMS Assignment`
            WHERE name = %(assignment_name)s
        """,
			{"assignment_name": assignment_name},
			as_dict=True,
		)

		if not assignment_data:
			return {"error": "Assignment not found"}

		assignment = assignment_data[0]

		# Get recipients
		recipients = frappe.db.sql(
			"""
            SELECT students
            FROM `tabAssignment Student`
            WHERE parent = %(assignment_name)s
            ORDER BY idx
        """,
			{"assignment_name": assignment_name},
			as_dict=True,
		)

		# Get quiz questions if it's a quiz assignment
		quiz_questions = []
		if assignment.get("type") == "Quiz/Multiple choice":
			quiz_questions = frappe.db.sql(
				"""
                SELECT question, question_type, option_a, option_b, option_c, option_d,
                       correct_answer, marks, points
                FROM `tabLMS Quiz Question`
                WHERE parent = %(assignment_name)s
                ORDER BY idx
            """,
				{"assignment_name": assignment_name},
				as_dict=True,
			)

		return {
			"success": True,
			"data": {"assignment": assignment, "recipients": recipients, "quiz_questions": quiz_questions},
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Assignment Detail Failed")
		return {"error": str(e)}


@frappe.whitelist()
def get_assignments_for_student(student_email):
	"""
	Get all assignments assigned to a specific student
	"""
	try:
		assignment_names = frappe.get_all(
			"PL Students",
			filters={"students": student_email},
			fields=["parent"],
		)

		assignments = frappe.get_all(
			"LMS Assignment",
			filters={"name": ["in", [a.parent for a in assignment_names]]},
			fields=["*"]
		)

		return {"success": True, "data": assignments, "count": len(assignments)}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Student Assignments Failed")
		return {"error": str(e)}


@frappe.whitelist()
def submit_assignment_response():
	"""
	Allow students to submit responses to assignments
	"""
	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		assignment_name = data.get("assignment_name")
		student_email = data.get("student_email")
		response_content = data.get("response_content", "")
		submitted_file = data.get("submitted_file", "")

		if not assignment_name or not student_email:
			return {"error": "assignment_name and student_email are required"}

		# Check if student is assigned to this assignment
		is_assigned = frappe.db.exists(
			"Assignment Student", {"parent": assignment_name, "students": student_email}
		)

		if not is_assigned:
			return {"error": "Student is not assigned to this assignment"}

		# Create assignment submission
		submission_name = generate_hash(length=10)
		creation_time = now()

		frappe.db.sql(
			"""
            INSERT INTO `tabAssignment Submission`
            (name, assignment, student, response_content, submitted_file, submission_date,
             creation, modified, modified_by, owner, docstatus)
            VALUES
            (%(name)s, %(assignment)s, %(student)s, %(response_content)s, %(submitted_file)s,
             %(submission_date)s, %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
        """,
			{
				"name": submission_name,
				"assignment": assignment_name,
				"student": student_email,
				"response_content": response_content,
				"submitted_file": submitted_file,
				"submission_date": creation_time,
				"creation": creation_time,
				"modified": creation_time,
				"modified_by": student_email,
				"owner": student_email,
			},
		)

		frappe.db.commit()

		return {
			"success": True,
			"message": "Assignment submitted successfully",
			"submission_name": submission_name,
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Assignment Submission Failed")
		return {"error": str(e)}


@frappe.whitelist()
def save_assignment(assignment, title, type, question):
	if not has_course_moderator_role() or not has_course_instructor_role():
		return

	if assignment:
		doc = frappe.get_doc("LMS Assignment", assignment)
	else:
		doc = frappe.get_doc({"doctype": "LMS Assignment"})

	doc.update({"title": title, "type": type, "question": question})
	doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_all_student_assignment(user, limit=None, **kwargs):
	"""
	Fetch all assignments where a given student is in the recipient list.
	"""

	# Step 1: Find all LMS Assignment IDs linked to this student
	student_links = frappe.get_all(
		"PL Students",
		filters={"students": user},
		fields=["parent"],
	)

	assignment_ids = [s.parent for s in student_links]

	if not assignment_ids:
		return []

	# Step 2: Fetch the assignments
	filters = {"name": ["in", assignment_ids]}
	filters.update(kwargs)
	user_assignments = frappe.get_all(
		"LMS Assignment",
		filters=filters,
		fields=["*"],
		limit=limit,
		order_by="creation desc",
	)

	result = []
	for a in user_assignments:
		quiz_questions = frappe.get_all(
			"LMS Quiz Question",
			filters={"parent": a.get("name"), "parenttype": "LMS Assignment"},
			fields=[
				"name",
				"question",
				"question_type",
				"marks",
				"option_a",
				"option_b",
				"option_c",
				"option_d",
				"correct_answer",
				"explanation",
			],
		)

		result.append(
			{
				"id": a.get("name"),
				"title": a.get("title"),
				"type": a.get("type"),
				"question": a.get("question"),
				"created_at": a.get("creation"),
				"description": a.get("instructions") or a.get("description"),
				"file": a.get("file"),
				"resource_link": a.get("resource_link"),
				"show_answers": a.get("show_answers"),
				"due_date": a.get("due_date"),
				"total_marks": a.get("total_score"),
				"submitted": a.get("submitted"),
				"drafted": a.get("drafted"),
				"grade_assignment": a.get("grade_assignment"),
				"is_public": a.get("public"),
				"status": a.get("status"),	
				"quiz_questions": [
					{
						"id": q.get("name"),
						"question": q.get("question"),
						"question_type": q.get("question_type"),
						"options": q.get("options"),
						"correct_answer": q.get("correct_answer"),
						"marks": q.get("marks"),
						"option_a": q.get("option_a"),
						"option_b": q.get("option_b"),
						"option_c": q.get("option_c"),
						"option_d": q.get("option_d"),
						"explanation": q.get("explanation"),
					}
					for q in quiz_questions
				],
				"subject": (
					{
						"id": a.get("subject"),
						"subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
					}
					if a.get("subject")
					else None
				),
				"educational_level": (
					{
						"id": a.get("educational_level"),
						"educational_level": frappe.db.get_value(
							"LMS Course Level", a.get("educational_level"), "education_level"
						),
					}
					if a.get("educational_level")
					else None
				),
			}
		)

	return {
			"success": True,
			"message": "Assignments fetched successfully",
			"data": result,
		}


@frappe.whitelist()
def get_all_instructor_assignment(user, limit=None, **kwargs):
	"""
	Fetch all assignments created by a given instructor.
	"""

	# Step 1: Fetch the assignments
	filters = {"owner": user}
	filters.update(kwargs)
	instructor_assignments = frappe.get_all(
		"LMS Assignment",
		filters=filters,
		fields=["*"],
		limit=limit,
		order_by="creation desc",
	)

	return {"success": True, "data": instructor_assignments, "count": len(instructor_assignments)}


@frappe.whitelist(allow_guest=True)
def get_assignment_details(assignment):
	assignments = frappe.get_all(
		"LMS Assignment",
		filters={"name": assignment},
		fields=["*"],
	)

	if not assignments:
		return {"success": False, "message": "Assignment not found"}

	# result = []
	assignment = assignments[0]
	quiz_questions = frappe.get_all(
			"LMS Quiz Question",
			filters={"parent": assignment.get("name"), "parenttype": "LMS Assignment"},	
			fields=[
				"name",
				"question",
				"question_type",
				"marks",
				"option_a",
				"option_b",
				"option_c",
				"option_d",
				"correct_answer",
				"explanation",
			],
		)

	result = {
				"id": assignment.get("name"),
				"title": assignment.get("title"),
				"type": assignment.get("type"),
				"question": assignment.get("question"),
				"created_at": assignment.get("creation"),
				"description": assignment.get("instructions") or assignment.get("description"),
				"file": assignment.get("file"),
				"resource_link": assignment.get("resource_link"),
				"show_answers": assignment.get("show_answers"),
				"due_date": assignment.get("due_date"),
				"total_marks": assignment.get("total_score"),
				"submitted": a.get("submitted"),
				"drafted": a.get("drafted"),
				"grade_assignment": a.get("grade_assignment"),
				"is_public": a.get("public"),
				"status": a.get("status"),
				"quiz_questions": [
					{
						"id": q.get("name"),
						"question": q.get("question"),
						"question_type": q.get("question_type"),
						"marks": q.get("marks"),
						"option_a": q.get("option_a"),
						"option_b": q.get("option_b"),
						"option_c": q.get("option_c"),
						"option_d": q.get("option_d"),
						"correct_answer": q.get("correct_answer"),
						"explanation": q.get("explanation"),
					}
					for q in quiz_questions
				],
				"subject": (
					{
						"id": a.get("subject"),
						"subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
					}
					if a.get("subject")
					else None
				),
				"educational_level": (
					{
						"id": a.get("educational_level"),
						"educational_level": frappe.db.get_value(
							"LMS Course Level", a.get("educational_level"), "education_level"
						),
					}
					if a.get("educational_level")
					else None
				),
		}

	return {
			"success": True,
			"message": "Assignments fetched successfully",
			"data": result,
		}


@frappe.whitelist()
def get_overdue_assignments(student):
	"""
	Fetch all assignments that are overdue (due date has passed and not submitted) for a specific student.
	"""
	from frappe.utils import getdate

	today = getdate()

	# Get all assignment IDs where this student is a recipient (from PL Students)
	student_links = frappe.get_all(
		"PL Students",
		filters={"students": student},
		fields=["parent"],
	)
	assignment_ids = [s.parent for s in student_links]

	if not assignment_ids:
		return {"success": True, "data": [], "count": 0}

	overdue_assignments = frappe.get_all(
		"LMS Assignment",
		filters={
			"name": ["in", assignment_ids],
			"due_date": ["<", today],
			"submitted": 0,
			"drafted": 0,
		},
		fields=["name", "title", "due_date", "owner", "type"],
		order_by="due_date asc",
	)

	return {"success": True, "data": overdue_assignments, "count": len(overdue_assignments)}
