# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import validate_url
from frappe.utils import get_datetime, now_datetime



class LMSAssignmentSubmission(Document):
	def validate(self):
		# self.validate_duplicates()
		self.validate_url()
		self.validate_status()

	# def validate_duplicates(self):
		# if frappe.db.exists(
		# 	"LMS Assignment Submission",
		# 	{"assignment": self.assignment, "member": self.member, "name": ["!=", self.name]},
		# ):
		# 	lesson_title = frappe.db.get_value("Course Lesson", self.lesson, "title")
		# 	frappe.throw(
		# 		_("Assignment for Lesson {0} by {1} already exists.").format(lesson_title, self.member_name)
		# 	)

	def validate_url(self):
		if self.type == "URL" and not validate_url(self.answer):
			frappe.throw(_("Please enter a valid URL."))

	def validate_status(self):
		if not self.is_new():
			doc_before_save = self.get_doc_before_save()
			if doc_before_save.status != self.status or doc_before_save.comments != self.comments:
				self.trigger_update_notification()

	def trigger_update_notification(self):
		notification = frappe._dict(
			{
				"subject": _("There has been an update on your submission for assignment {0}").format(
					self.assignment_title
				),
				"email_content": self.comments,
				"document_type": self.doctype,
				"document_name": self.name,
				"for_user": self.owner,
				"from_user": self.evaluator,
				"type": "Alert",
				"link": f"/assignment-submission/{self.assignment}/{self.name}",
			}
		)
		make_notification_logs(notification, [self.member])

	def auto_grade_quiz(self):
		"""
		Go through quiz_questions from assignment, compare with answers in self.quiz_answers.
		Calculate percentage based on test_score and track attempts PER STUDENT.
		"""
		try:
			assignment = frappe.get_doc("LMS Assignment", self.assignment)

			# Check if attempts are available - COUNT PER STUDENT
			attempts_allowed = assignment.get("attempts_allowed", 1)

			# Count how many times THIS STUDENT has already submitted THIS ASSIGNMENT
			# Note: We count existing submissions BEFORE this one is saved
			attempts_made = frappe.db.count(
				"LMS Assignment Submission",
				{"assignment": self.assignment, "member": self.member, "name": ["!=", self.name]}
			)

			if attempts_made >= attempts_allowed:
				frappe.throw(f"No attempts remaining for this assignment. ({attempts_made}/{attempts_allowed} used)")

			total_score = 0
			max_possible_score = 0

			# Get quiz questions
			quiz_questions = assignment.get("quiz_questions", [])

			if not quiz_questions:
				frappe.throw("No quiz questions found in this assignment.")

			# Create a dict of student answers for easy lookup
			student_answers = {ans.question: ans.selected_option for ans in self.quiz_answers}

			# Clear existing quiz_answers to avoid duplicates
			self.quiz_answers = []

			for q in quiz_questions:
				# Get marks for this question (default to 1 if not set)
				question_marks = q.get("marks", 1)
				max_possible_score += question_marks

				# Get student's selected option
				selected = student_answers.get(q.name, "")

				# Check if answer is correct
				correct_answer = q.get("correct_answer", "").strip()
				is_correct = selected.strip() == correct_answer if selected and correct_answer else False
				marks = question_marks if is_correct else 0
				total_score += marks

				# Append row
				self.append(
					"quiz_answers",
					{
						"question": q.name,
						"selected_option": selected,
						"is_correct": 1 if is_correct else 0,
						"marks_awarded": marks,
					}
				)

			# Get test_score from assignment (default to 100 if not set)
			test_score_value = float(assignment.get("test_score") or 100)

			# Calculate percentage based on marks obtained vs max possible
			if max_possible_score > 0:
				percentage = (total_score / max_possible_score) * 100
				# Scale to test_score
				final_score = (percentage / 100) * test_score_value
			else:
				percentage = 0
				final_score = 0

			# Set scores
			self.score = round(final_score, 2)
			self.total_score = int(test_score_value)

			# Set status based on percentage (50% pass threshold)
			self.status = "Pass" if percentage >= 50 else "Fail"

			# Set comments with detailed breakdown
			self.comments = f"""Auto graded: {total_score}/{max_possible_score} correct
Percentage: {percentage:.2f}%
Final Score: {final_score:.2f}/{test_score_value}"""

			# NO NEED TO INCREMENT attempts_made - WE COUNT SUBMISSIONS DYNAMICALLY
			self.save(ignore_permissions=True)

		except Exception as e:
			frappe.log_error(title="Auto Grade Quiz Error", message=frappe.get_traceback())
			raise


@frappe.whitelist()
def upload_assignment(
	assignment_attachment=None,
	answer=None,
	assignment=None,
	lesson=None,
	status="Not Graded",
	comments=None,
	submission=None,
):
	if frappe.session.user == "Guest":
		return

	assignment_details = frappe.db.get_value(
		"LMS Assignment", assignment, ["type", "grade_assignment"], as_dict=1
	)
	assignment_type = assignment_details.type

	# Validation
	if assignment_type in ["Essay/Written task", "Practical task"] and not answer:
		frappe.throw(_("Please enter the URL for assignment submission."))
	if assignment_type == "Video submission" and not assignment_attachment:
		frappe.throw(_("Please upload the assignment file."))
	if assignment_type == "URL" and not validate_url(answer):
		frappe.throw(_("Please enter a valid URL."))

	assignment_doc = frappe.get_doc("LMS Assignment", assignment)

	# Check due date: disallow submissions past due_date
	due_date = assignment_doc.get("due_date")
	if due_date:
		if now_datetime() > get_datetime(due_date):
			frappe.throw(_("Assignment due date has passed. You cannot submit this assignment."))

	attempts_allowed = assignment_doc.get("attempts_allowed", 1)

	# Count existing submissions for THIS USER for THIS ASSIGNMENT
	existing_attempts = frappe.db.count(
		"LMS Assignment Submission",
		{"assignment": assignment, "member": frappe.session.user}
	)

	# For NEW submissions only, check if attempts exceeded
	if not submission:
		if existing_attempts >= attempts_allowed:
			frappe.throw(_(
				f"You have used all your attempts for this assignment. "
				f"({existing_attempts}/{attempts_allowed} used)"
			))

		# Create new submission
		doc = frappe.get_doc({
			"doctype": "LMS Assignment Submission",
			"assignment": assignment,
			"lesson": lesson,
			"member": frappe.session.user,
			"type": assignment_type,
			"assignment_attachment": assignment_attachment,
			"answer": answer,
			"comments": comments,
			"status": "Not Applicable"
				if assignment_type == "Text" and not assignment_details.grade_assignment
				else status,
		})
		doc.save(ignore_permissions=True)

		# Update Assignment Status to Submitted (on first submission)
		if existing_attempts == 0:
			frappe.db.set_value("LMS Assignment", assignment, {
				"status": "Submitted",
				"submitted": 1
			})

		# Calculate remaining attempts after this new submission
		attempts_remaining = attempts_allowed - (existing_attempts + 1)

	else:
		# Update existing submission
		doc = frappe.get_doc("LMS Assignment Submission", submission)

		# Only update fields that are provided, preserve status if already graded
		if assignment_attachment:
			doc.assignment_attachment = assignment_attachment
		if answer:
			doc.answer = answer
		if comments:
			doc.comments = comments

		# Only update status if not already graded
		if doc.status not in ["Pass", "Fail", "Graded"]:
			doc.status = "Not Applicable" \
				if assignment_type == "Text" and not assignment_details.grade_assignment \
				else status

		doc.save(ignore_permissions=True)

		# Attempts remain the same for updates
		attempts_remaining = attempts_allowed - existing_attempts

	return {
		"message": "Assignment submitted successfully." if not submission else "Assignment updated successfully.",
		"submission": doc.name,
		"attempts_remaining": attempts_remaining,
		"attempts_made": existing_attempts + (0 if submission else 1),
		"attempts_allowed": attempts_allowed,
	}

@frappe.whitelist()
def grade_assignment(name, result, comments, score, totalScore, file,correction_file):
	doc = frappe.get_doc("LMS Assignment Submission", name)
	doc.status = result
	doc.comments = comments
	doc.score = score
	doc.total_score = totalScore
	doc.file = file
	doc.correction_file = correction_file
	doc.save(ignore_permissions=True)
	return {"message": "Assignment graded successfully."}

@frappe.whitelist()
def submit_quiz(assignment, answers):
	"""
	answers = [{ "question": "QQ-230924-00001", "selected_option": "A" }, ...]
	"""
	try:
		if frappe.session.user == "Guest":
			frappe.throw(_("Login required"))

		# Parse answers if they come as JSON string
		if isinstance(answers, str):
			import json
			answers = json.loads(answers)

		assignment_doc = frappe.get_doc("LMS Assignment", assignment)

		if assignment_doc.type != "Quiz/Multiple choice":
			frappe.throw(_("Assignment is not a quiz."))

		# Check due date: disallow submissions past due_date
		due_date = assignment_doc.get("due_date")
		if due_date:
			if now_datetime() > get_datetime(due_date):
				frappe.throw(_("Assignment due date has passed. You cannot submit this quiz."))

		# Get attempts tracking - COUNT PER STUDENT
		attempts_allowed = assignment_doc.get("attempts_allowed", 1)

		# Count existing submissions for THIS USER for THIS ASSIGNMENT
		attempts_made = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": assignment, "member": frappe.session.user}
		)

		# Check if user has exceeded attempts
		if attempts_made >= attempts_allowed:
			frappe.throw(_(f"You have used all your attempts for this assignment. ({attempts_made}/{attempts_allowed} used)"))

		# Create submission doc
		submission = frappe.get_doc(
			{
				"doctype": "LMS Assignment Submission",
				"assignment": assignment,
				"member": frappe.session.user,
				"type": assignment_doc.type,
				"status": "Not Graded",
			}
		)

		# Add quiz answers to submission
		for ans in answers:
			submission.append(
				"quiz_answers",
				{
					"question": ans.get("question"),
					"selected_option": ans.get("selected_option", ""),
				}
			)

		submission.insert(ignore_permissions=True)

		# Now run auto-grading
		submission.auto_grade_quiz()

		# Update Assignment status to Submitted (only on first submission by this user)
		if attempts_made == 0:
			frappe.db.set_value("LMS Assignment", assignment, {
				"status": "Submitted",
				"submitted": 1
			})

		frappe.db.commit()

		# Reload submission to get updated values
		submission.reload()

		# Recalculate attempts after this submission (now includes this new one)
		updated_attempts_made = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": assignment, "member": frappe.session.user}
		)
		attempts_remaining = attempts_allowed - updated_attempts_made

		# Prepare response with detailed answers
		detailed_answers = []
		for quiz_ans in submission.quiz_answers:
			detailed_answers.append(
				{
					"question": quiz_ans.question,
					"selected_option": quiz_ans.selected_option,
					"is_correct": quiz_ans.get("is_correct", 0),
					"marks_awarded": quiz_ans.get("marks_awarded", 0),
				}
			)

		return {
			"submission": submission.name,
			"score": submission.get("score", 0),
			"total_score": submission.get("total_score", 100),
			"percentage": round((submission.get("score", 0) / submission.get("total_score", 100) * 100), 2) if submission.get("total_score") else 0,
			"status": submission.status,
			"answers": detailed_answers,
			"attempts_made": updated_attempts_made,
			"attempts_allowed": attempts_allowed,
			"attempts_remaining": attempts_remaining if attempts_remaining > 0 else 0,
			"comments": submission.get("comments", "")
		}

	except Exception as e:
		frappe.log_error(title="Submit Quiz Error", message=frappe.get_traceback())
		frappe.throw(_(f"Error submitting quiz: {str(e)}"))

@frappe.whitelist()
def get_student_submitted_assignments(student):
	"""
	Get all assignments submitted by a student with enriched user details and quiz answers.
	"""
	students_link = frappe.get_all(
		"PL Students",
		filters={"students": student},
		fields=["parent"],
	)
	assignment_ids = [s.parent for s in students_link]

	if not assignment_ids:
		return {"success": True, "data": []}

	submitted_assignments = frappe.get_all(
		"LMS Assignment Submission",
		filters={"assignment": ["in", assignment_ids], "member": student},
		fields=["*"],
		order_by="creation desc",
	)

	# Enrich submissions with user details and quiz answers
	enriched_submissions = []
	for submission in submitted_assignments:
		# Get member (student) details
		member_details = {}
		if submission.get("member"):
			member_user = frappe.get_all(
				"User",
				filters={"name": submission.get("member")},
				fields=["full_name", "email", "user_image"],
				limit=1
			)
			if member_user:
				member_details = {
					"full_name": member_user[0].get("full_name", ""),
					"email": member_user[0].get("email", ""),
					"user_image": member_user[0].get("user_image", "")
				}

		# Get owner (instructor) details from submission
		owner_details = None
		if submission.get("owner"):
			owner_user = frappe.get_all(
				"User",
				filters={"name": submission.get("owner")},
				fields=["full_name", "email", "user_image"],
				limit=1
			)
			if owner_user:
				owner_details = {
					"full_name": owner_user[0].get("full_name", ""),
					"email": owner_user[0].get("email", ""),
					"user_image": owner_user[0].get("user_image", "")
				}

		# Get quiz answers for this submission if it's a quiz
		quiz_answers = []
		if submission.get("type") == "Quiz/Multiple choice":
			quiz_answers = frappe.get_all(
				"LMS Quiz Answer",
				filters={"parent": submission.get("name")},
				fields=[
					"name",
					"question",
					"selected_option",
					"is_correct",
					"marks_awarded"
				],
				order_by="idx asc"
			)

		# Get assignment details
		assignment_details = frappe.get_all(
			"LMS Assignment",
			filters={"name": submission.get("assignment")},
			fields=["title", "type", "test_score", "attempts_allowed","instructions","resource_link"],
			limit=1
		)
		assignment_info = assignment_details[0] if assignment_details else {}

		# COUNT ATTEMPTS FOR THIS SPECIFIC STUDENT
		attempts_made = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": submission.get("assignment"), "member": student}
		)

		# Build enriched submission object
		enriched_submission = {
			"id": submission.get("name"),
			"assignment_id": submission.get("assignment"),
			"assignment_title": submission.get("assignment_title", ""),
			"assignment_type": submission.get("type", ""),
			"member": member_details,  # ← Student details
			"owner": owner_details,  # ← Instructor/Creator details
			"status": submission.get("status", ""),
			"score": submission.get("score"),
			"total_score": submission.get("total_score"),
			"percentage": round((submission.get("score", 0) / submission.get("total_score", 100) * 100), 2) if submission.get("total_score") else 0,
			"comments": submission.get("comments", ""),
			"question": submission.get("question", ""),
			"answer": submission.get("answer", ""),
			"assignment_attachment": submission.get("assignment_attachment", ""),
			"file": submission.get("file", ""),
			"created_at": submission.get("creation"),
			"modified_at": submission.get("modified"),
			"quiz_answers": quiz_answers,
			"attempts_made": attempts_made,
			"attempts_allowed": assignment_info.get("attempts_allowed", 1),
			"assignment_instructions" : assignment_info.get("instructions", ""),
			"resource_link": assignment_info.get("resource_link", "")
		}

		enriched_submissions.append(enriched_submission)

	return {"success": True, "data": enriched_submissions}

@frappe.whitelist()
def get_all_assignment_submissions(tutor):
	"""
	Get all submissions for assignments created by a tutor with enriched user details.
	"""
	assignments = frappe.get_all(
		"LMS Assignment",
		filters={"owner": tutor},
		fields=["name", "title", "type", "test_score", "attempts_allowed"],
	)

	if not assignments:
		return {"success": True, "data": []}

	assignment_ids = [a.name for a in assignments]

	# Create a lookup dict for assignment info
	assignment_lookup = {a.name: a for a in assignments}

	submissions = frappe.get_all(
		"LMS Assignment Submission",
		filters={"assignment": ["in", assignment_ids]},
		fields=["*"],
		order_by="creation desc",
	)

	# Enrich submissions with user details and quiz answers
	enriched_submissions = []
	for submission in submissions:
		# Get member (student) details
		member_details = {}
		if submission.get("member"):
			member_user = frappe.get_all(
				"User",
				filters={"name": submission.get("member")},
				fields=["full_name", "email", "user_image"],
				limit=1
			)
			if member_user:
				member_details = {
					"full_name": member_user[0].get("full_name", ""),
					"email": member_user[0].get("email", ""),
					"user_image": member_user[0].get("user_image", "")
				}

		# Get owner (instructor/tutor) details
		owner_details = {}
		if submission.get("owner"):
			owner_user = frappe.get_all(
				"User",
				filters={"name": submission.get("owner")},
				fields=["full_name", "email", "user_image"],
				limit=1
			)
			if owner_user:
				owner_details = {
					"full_name": owner_user[0].get("full_name", ""),
					"email": owner_user[0].get("email", ""),
					"user_image": owner_user[0].get("user_image", "")
				}

		# Get quiz answers for this submission if it's a quiz
		quiz_answers = []
		if submission.get("type") == "Quiz/Multiple choice":
			quiz_answers = frappe.get_all(
				"LMS Quiz Answer",
				filters={"parent": submission.get("name")},
				fields=[
					"name",
					"question",
					"selected_option",
					"is_correct",
					"marks_awarded"
				],
				order_by="idx asc"
			)

		# Get assignment info from lookup
		assignment_info = assignment_lookup.get(submission.get("assignment"), {})

		# COUNT ATTEMPTS FOR THIS SPECIFIC STUDENT AND ASSIGNMENT
		attempts_made = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": submission.get("assignment"), "member": submission.get("member")}
		)

		# Build enriched submission object
		enriched_submission = {
			"id": submission.get("name"),
			"assignment_id": submission.get("assignment"),
			"assignment_title": submission.get("assignment_title", ""),
			"assignment_type": submission.get("type", ""),
			"member": member_details,  # ← Student details
			"owner": owner_details,  # ← Instructor/Creator details
			"status": submission.get("status", ""),
			"score": submission.get("score"),
			"total_score": submission.get("total_score"),
			"percentage": round((submission.get("score", 0) / submission.get("total_score", 100) * 100), 2) if submission.get("total_score") else 0,
			"comments": submission.get("comments", ""),
			"question": submission.get("question", ""),
			"answer": submission.get("answer", ""),
			"assignment_attachment": submission.get("assignment_attachment", ""),
			"file": submission.get("file", ""),
			"created_at": submission.get("creation"),
			"modified_at": submission.get("modified"),
			"quiz_answers": quiz_answers,
			"attempts_made": attempts_made,
			"attempts_allowed": assignment_info.get("attempts_allowed", 1),
			"assignment_instructions" : assignment_info.get("instructions", ""),
			"resource_link": assignment_info.get("resource_link", "")
		}

		enriched_submissions.append(enriched_submission)

	return {"success": True, "data": enriched_submissions}

@frappe.whitelist()
def get_assignment_submission_details(submission_id):
	"""
	Get detailed information about a specific assignment submission including selected answers.
	"""
	try:
		# Check if submission exists
		if not frappe.db.exists("LMS Assignment Submission", submission_id):
			return {
				"success": False,
				"message": "Submission not found",
				"data": None
			}

		# Get submission details
		submission = frappe.get_doc("LMS Assignment Submission", submission_id)

		# Get assignment details
		assignment = frappe.get_doc("LMS Assignment", submission.assignment)

		# Get quiz answers with full details
		quiz_answers = []
		for ans in submission.quiz_answers:
			# Get the quiz question details from assignment
			quiz_question = None
			for q in assignment.quiz_questions:
				if q.name == ans.question:
					quiz_question = q
					break

			# Get LMS Question details if available
			question_text = ""
			if quiz_question and quiz_question.question:
				lms_question = frappe.get_doc("LMS Question", quiz_question.question)
				question_text = lms_question.question

			quiz_answers.append({
				"question_id": ans.question,
				"question_text": question_text or (quiz_question.question if quiz_question else ""),
				"selected_option": ans.selected_option,
				"correct_answer": quiz_question.correct_answer if quiz_question else None,
				"is_correct": ans.get("is_correct", 0),
				"marks_awarded": ans.get("marks_awarded", 0),
				"marks_possible": quiz_question.marks if quiz_question else 0,
				"option_a": quiz_question.option_a if quiz_question else "",
				"option_b": quiz_question.option_b if quiz_question else "",
				"option_c": quiz_question.option_c if quiz_question else "",
				"option_d": quiz_question.option_d if quiz_question else "",
				"explanation": quiz_question.explanation if quiz_question else ""
			})

		# COUNT ATTEMPTS FOR THIS SPECIFIC STUDENT
		attempts_made = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": submission.assignment, "member": submission.member}
		)

		# Build response
		response_data = {
			"submission_id": submission.name,
			"assignment_id": submission.assignment,
			"assignment_title": assignment.title,
			"assignment_type": assignment.type,
			"member": submission.member,
			"member_name": submission.member_name,
			"status": submission.status,
			"score": submission.score,
			"total_score": submission.total_score,
			"percentage": round((submission.score / submission.total_score * 100), 2) if submission.total_score else 0,
			"comments": submission.comments,
			"created_at": submission.creation,
			"modified_at": submission.modified,
			"quiz_answers": quiz_answers,
			"assignment_file": assignment.file,
			"attempts_made": attempts_made,
			"assignment_attachment": submission.assignment_attachment,
			"attempts_allowed": assignment.get("attempts_allowed", 1),
			"duration": assignment.get("duration", 0),
			"subject": (
			{
				"id": assignment.subject,
				"subject_name": frappe.db.get_value("Subject", assignment.subject, "subject_name")
			} if assignment.subject else None
)
		}

		return {
			"success": True,
			"data": response_data
		}

	except Exception as e:
		frappe.log_error(f"Error in get_assignment_submission_details: {str(e)}")
		return {
			"success": False,
			"message": f"Error fetching submission details: {str(e)}",
			"data": None
		}
