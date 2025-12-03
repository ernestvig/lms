# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from lms.lms.utils import has_course_instructor_role, has_course_moderator_role


class LMSAssignment(Document):
    pass

def mark_overdue_on_save(doc, method):
    """Doc event: set status to 'Overdue' if due_date is in the past.

    Intended to be wired in hooks.py as a doc_event for the LMS Assignment doctype
    (e.g. "validate" or "on_update").
    """
    try:
        if getattr(doc, "due_date", None):
            from frappe.utils import get_datetime, now_datetime
            # compare as datetimes to handle both date and datetime fields
            if get_datetime(doc.due_date) < now_datetime():
                # don't override graded/submitted statuses if that's undesired; adjust as needed
                if doc.status not in ("Overdue", "Graded"):
                    doc.status = "Overdue"
    except Exception as e:
        frappe.log_error(f"mark_overdue_on_save: {e}", "Assignment Hook Error")

@frappe.whitelist()
def create_assignment():
    """
    Create an enhanced assignment with proper LMS Question and Quiz Question structure.
    """
    import json
    from frappe.utils import getdate

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
        assignment_doc.educational_level = data.get("educational_level", "")
        assignment_doc.due_date = data.get("due_date", "0000-00-00 00:00:00")
        assignment_doc.late_submission = 1 if data.get("late_submission", False) else 0
        assignment_doc.set_reminders = 1 if data.get("set_reminders", False) else 0
        assignment_doc.submitted = 0
        assignment_doc.drafted = data.get("drafted", False)
        assignment_doc.public = data.get("public", 0)
        assignment_doc.attempts_allowed = data.get("attempts_allowed", 1)
        assignment_doc.duration = data.get("duration", 0)

        # === Add Recipients ===
        recipients_created = []
        recipients_failed = []

        if "recipient" in data and isinstance(data["recipient"], list):
            for recipient_data in data["recipient"]:
                student_email = recipient_data.get("students")
                if not student_email:
                    recipients_failed.append({"email": "N/A", "reason": "No email provided"})
                    continue

                # Check if student exists
                student_exists = frappe.db.exists("User", student_email)
                if not student_exists:
                    recipients_failed.append({"email": student_email, "reason": "User not found"})
                    continue

                # Add recipient to the assignment
                try:
                    assignment_doc.append("recipient", {"students": student_email})
                    recipients_created.append(student_email)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to add recipient {student_email}: {str(e)}",
                        "Assignment Recipient Error"
                    )
                    recipients_failed.append({"email": student_email, "reason": str(e)})

        # === Create LMS Questions first, then Quiz Questions ===
        lms_questions_created = []
        quiz_questions_created = []

        if (
            data.get("type") == "Quiz/Multiple choice"
            and "quiz_questions" in data
            and isinstance(data["quiz_questions"], list)
        ):
            for idx, question_data in enumerate(data["quiz_questions"]):
                if not question_data.get("question"):
                    continue

                try:
                    # Step 1: Create LMS Question
                    lms_question_doc = frappe.new_doc("LMS Question")
                    lms_question_doc.question = question_data.get("question", "")
                    lms_question_doc.type = "Choices"  # Must be "Choices" for multiple choice
                    lms_question_doc.multiple = 0  # Single correct answer
                    lms_question_doc.selected_answer = question_data.get("selected_answer","")

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
                        "selected_answer": question_data.get("selected_answer",""),
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

                except Exception as e:
                    frappe.log_error(
                        f"Failed to create quiz question at index {idx}: {str(e)}",
                        "Assignment Quiz Question Error"
                    )
                    return {
                        "success": False,
                        "error": f"Failed to create quiz question: {str(e)}"
                    }

        # Insert the assignment with quiz questions
        assignment_doc.insert(ignore_permissions=True)

        # === Create Student Status Records for Recipients ===
        from lms.lms.doctype.lms_assignment_student_status.lms_assignment_student_status import create_student_status

        student_statuses_created = []
        for recipient_email in recipients_created:
            try:
                status_name = create_student_status(assignment_doc.name, recipient_email)
                student_statuses_created.append({
                    "student": recipient_email,
                    "status_id": status_name
                })
            except Exception as e:
                frappe.log_error(
                    f"Failed to create student status for {recipient_email}: {str(e)}",
                    "Student Status Creation Error"
                )

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
                "recipients_failed_count": len(recipients_failed),
                "lms_questions_count": len(lms_questions_created),
                "quiz_questions_count": len(quiz_questions_created),
                "student_statuses_created": len(student_statuses_created),
                "grade_assignment": bool(assignment_doc.grade_assignment),
                "show_answer": bool(assignment_doc.show_answer),
                "recipients": recipients_created,
                "lms_questions": lms_questions_created,
                "quiz_questions": quiz_questions_created,
                "status": assignment_doc.status,
                "drafted": bool(assignment_doc.drafted),
                "public": bool(assignment_doc.public),
                "duration": str(assignment_doc.duration) if assignment_doc.duration else None,
                "attempts_allowed": assignment_doc.attempts_allowed
            },
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Enhanced Assignment Creation Failed")
        return {
            "success": False,
            "error": str(e),
            "traceback": frappe.get_traceback()
        }

@frappe.whitelist()
def update_assignment():
    """
    Update an existing assignment with proper LMS Question and Quiz Question structure.
    """
    import json
    from frappe.utils import getdate

    try:
        data = {}
        if frappe.request and frappe.request.data:
            data = json.loads(frappe.request.data)

        # Validate required fields
        if not data.get("assignment_name"):
            return {"error": "Missing required field: assignment_name"}

        # Check if assignment exists
        if not frappe.db.exists("LMS Assignment", data.get("assignment_name")):
            return {"error": f"Assignment {data.get('assignment_name')} not found"}

        # Get the existing assignment
        assignment_doc = frappe.get_doc("LMS Assignment", data.get("assignment_name"))

        # Parse and validate due date if provided
        if data.get("due_date"):
            try:
                due_date = getdate(data.get("due_date"))
                assignment_doc.due_date = data.get("due_date") or due_date
            except ValueError:
                return {"error": "Invalid due_date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"}

        # Validate assignment type if provided
        if data.get("type"):
            valid_types = ["Quiz/Multiple choice", "Practical task", "Video submission", "Essay/Written task"]
            if data.get("type") not in valid_types:
                return {"error": f"Invalid assignment type. Must be one of: {', '.join(valid_types)}"}

        # === Update basic fields ===
        if "title" in data:
            assignment_doc.title = data.get("title")
        if "question" in data:
            assignment_doc.question = data.get("question")
        if "type" in data:
            assignment_doc.type = data.get("type")
        if "grade_assignment" in data:
            assignment_doc.grade_assignment = 1 if data.get("grade_assignment") else 0
        if "show_answer" in data:
            assignment_doc.show_answer = 1 if data.get("show_answer") else 0
        if "answer" in data:
            assignment_doc.answer = data.get("answer")
        if "instructions" in data:
            assignment_doc.instructions = data.get("instructions")
        if "file" in data:
            assignment_doc.file = data.get("file")
        if "resource_link" in data:
            assignment_doc.resource_link = data.get("resource_link")
        if "subject" in data:
            assignment_doc.subject = data.get("subject")
        if "test_score" in data:
            assignment_doc.test_score = data.get("test_score")
        if "status" in data:
            assignment_doc.status = "Pending"
        if "educational_level" in data:
            assignment_doc.educational_level = data.get("educational_level")
        if "late_submission" in data:
            assignment_doc.late_submission = 1 if data.get("late_submission") else 0
        if "set_reminders" in data:
            assignment_doc.set_reminders = 1 if data.get("set_reminders") else 0
        if "submitted" in data:
            assignment_doc.submitted = 0
        if "drafted" in data:
            assignment_doc.drafted = 1 if data.get("drafted") == 1 else 0
        if "public" in data:
            assignment_doc.public = 1 if data.get("drafted") == 0 else 0
        if "duration" in data:
            assignment_doc.duration = data.get("duration", 0)
        if "attempts_allowed" in data:
            assignment_doc.attempts_allowed = data.get("attempts_allowed", 1)

        # === Update Recipients ===
        from lms.lms.doctype.lms_assignment_student_status.lms_assignment_student_status import create_student_status

        recipients_updated = []
        recipients_added = []
        recipients_removed = []
        recipients_failed = []

        if "recipient" in data and isinstance(data["recipient"], list):
            # Get current recipients
            current_recipients = {r.students for r in assignment_doc.recipient}
            new_recipients = {r.get("students") for r in data["recipient"] if r.get("students")}

            # Remove recipients not in the new list
            recipients_to_remove = current_recipients - new_recipients
            for recipient_row in assignment_doc.recipient[:]:
                if recipient_row.students in recipients_to_remove:
                    assignment_doc.remove(recipient_row)
                    recipients_removed.append(recipient_row.students)

                    # Delete student status record
                    status_record = frappe.db.exists(
                        "LMS Assignment Student Status",
                        {"assignment": assignment_doc.name, "student": recipient_row.students}
                    )
                    if status_record:
                        frappe.delete_doc("LMS Assignment Student Status", status_record, ignore_permissions=True)

            # Add new recipients
            recipients_to_add = new_recipients - current_recipients
            for student_email in recipients_to_add:
                # Check if student exists
                student_exists = frappe.db.exists("User", student_email)
                if not student_exists:
                    recipients_failed.append({"email": student_email, "reason": "User not found"})
                    continue

                try:
                    assignment_doc.append("recipient", {"students": student_email})
                    recipients_added.append(student_email)

                    # Create student status record for new recipient
                    create_student_status(assignment_doc.name, student_email)

                except Exception as e:
                    frappe.log_error(
                        f"Failed to add recipient {student_email}: {str(e)}",
                        "Assignment Recipient Update Error"
                    )
                    recipients_failed.append({"email": student_email, "reason": str(e)})

            # Existing recipients that remain
            recipients_updated = list(current_recipients & new_recipients)

        # === Update Quiz Questions ===
        lms_questions_updated = []
        lms_questions_created = []
        lms_questions_deleted = []
        quiz_questions_updated = []

        # Store existing LMS Question names for cleanup
        existing_lms_questions = []
        if assignment_doc.quiz_questions:
            existing_lms_questions = [q.question for q in assignment_doc.quiz_questions if q.question]

        if (
            data.get("type") == "Quiz/Multiple choice"
            and "quiz_questions" in data
            and isinstance(data["quiz_questions"], list)
        ):
            # Clear existing quiz questions
            assignment_doc.quiz_questions = []

            # Track new LMS questions created
            new_lms_questions = []

            for idx, question_data in enumerate(data["quiz_questions"]):
                if not question_data.get("question"):
                    continue

                try:
                    lms_question_doc = None

                    # Check if updating existing question (by looking for lms_question_name)
                    if question_data.get("lms_question_name"):
                        # Update existing LMS Question
                        if frappe.db.exists("LMS Question", question_data.get("lms_question_name")):
                            lms_question_doc = frappe.get_doc("LMS Question", question_data.get("lms_question_name"))

                            # Update fields
                            lms_question_doc.question = question_data.get("question", "")
                            lms_question_doc.type = "Choices"
                            lms_question_doc.multiple = 0

                            # Update options
                            lms_question_doc.option_1 = question_data.get("option_a", "")
                            lms_question_doc.option_2 = question_data.get("option_b", "")
                            lms_question_doc.option_3 = question_data.get("option_c", "")
                            lms_question_doc.option_4 = question_data.get("option_d", "")

                            # Update explanations
                            explanation = question_data.get("explanation", "")
                            lms_question_doc.explanation_1 = explanation
                            lms_question_doc.explanation_2 = explanation
                            lms_question_doc.explanation_3 = explanation
                            lms_question_doc.explanation_4 = explanation

                            # Update correct answer
                            correct_answer = question_data.get("correct_answer", "A").upper()
                            lms_question_doc.is_correct_1 = 0
                            lms_question_doc.is_correct_2 = 0
                            lms_question_doc.is_correct_3 = 0
                            lms_question_doc.is_correct_4 = 0

                            if correct_answer == "A":
                                lms_question_doc.is_correct_1 = 1
                            elif correct_answer == "B":
                                lms_question_doc.is_correct_2 = 1
                            elif correct_answer == "C":
                                lms_question_doc.is_correct_3 = 1
                            elif correct_answer == "D":
                                lms_question_doc.is_correct_4 = 1
                            else:
                                lms_question_doc.is_correct_1 = 1

                            lms_question_doc.save(ignore_permissions=True)
                            lms_questions_updated.append({
                                "name": lms_question_doc.name,
                                "question": question_data.get("question", "")
                            })

                    # Create new LMS Question if not updating existing
                    if not lms_question_doc:
                        lms_question_doc = frappe.new_doc("LMS Question")
                        lms_question_doc.question = question_data.get("question", "")
                        lms_question_doc.type = "Choices"
                        lms_question_doc.multiple = 0

                        # Set options
                        lms_question_doc.option_1 = question_data.get("option_a", "")
                        lms_question_doc.option_2 = question_data.get("option_b", "")
                        lms_question_doc.option_3 = question_data.get("option_c", "")
                        lms_question_doc.option_4 = question_data.get("option_d", "")

                        # Set explanations
                        explanation = question_data.get("explanation", "")
                        lms_question_doc.explanation_1 = explanation
                        lms_question_doc.explanation_2 = explanation
                        lms_question_doc.explanation_3 = explanation
                        lms_question_doc.explanation_4 = explanation

                        # Set correct answer
                        correct_answer = question_data.get("correct_answer", "A").upper()
                        lms_question_doc.is_correct_1 = 0
                        lms_question_doc.is_correct_2 = 0
                        lms_question_doc.is_correct_3 = 0
                        lms_question_doc.is_correct_4 = 0

                        if correct_answer == "A":
                            lms_question_doc.is_correct_1 = 1
                        elif correct_answer == "B":
                            lms_question_doc.is_correct_2 = 1
                        elif correct_answer == "C":
                            lms_question_doc.is_correct_3 = 1
                        elif correct_answer == "D":
                            lms_question_doc.is_correct_4 = 1
                        else:
                            lms_question_doc.is_correct_1 = 1

                        lms_question_doc.insert(ignore_permissions=True)
                        lms_questions_created.append({
                            "name": lms_question_doc.name,
                            "question": question_data.get("question", "")
                        })

                    new_lms_questions.append(lms_question_doc.name)

                    # Add Quiz Question row
                    correct_answer = question_data.get("correct_answer", "A").upper()
                    quiz_question_row = {
                        "question": lms_question_doc.name,
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
                    quiz_questions_updated.append({
                        "lms_question": lms_question_doc.name,
                        "question_text": question_data.get("question", ""),
                        "correct_answer": correct_answer,
                        "marks": question_data.get("marks", 1)
                    })

                except Exception as e:
                    frappe.log_error(
                        f"Failed to update/create quiz question at index {idx}: {str(e)}",
                        "Assignment Quiz Question Update Error"
                    )
                    return {
                        "success": False,
                        "error": f"Failed to update/create quiz question: {str(e)}"
                    }

            # Save assignment FIRST to remove child table links
            assignment_doc.save(ignore_permissions=True)
            frappe.db.commit()

            # NOW delete orphaned LMS Questions (after the links are removed from DB)
            orphaned_questions = set(existing_lms_questions) - set(new_lms_questions)
            for lms_question_name in orphaned_questions:
                if frappe.db.exists("LMS Question", lms_question_name):
                    try:
                        # Check if this question is used in other assignments
                        other_usage = frappe.db.sql("""
                            SELECT parent
                            FROM `tabLMS Quiz Question`
                            WHERE question = %s AND parent != %s
                            LIMIT 1
                        """, (lms_question_name, assignment_doc.name))

                        if not other_usage:
                            frappe.delete_doc("LMS Question", lms_question_name, ignore_permissions=True)
                            lms_questions_deleted.append(lms_question_name)
                    except Exception as e:
                        frappe.log_error(
                            f"Failed to delete orphaned LMS Question {lms_question_name}: {str(e)}",
                            "LMS Question Deletion Error"
                        )

        elif assignment_doc.type == "Quiz/Multiple choice" and "quiz_questions" in data and not data["quiz_questions"]:
            # If changing from quiz type or clearing all questions
            # Clear quiz questions first
            assignment_doc.quiz_questions = []

            # Save assignment to remove child table links from database
            assignment_doc.save(ignore_permissions=True)
            frappe.db.commit()

            # Then delete existing LMS Questions if not used elsewhere
            for lms_question_name in existing_lms_questions:
                if frappe.db.exists("LMS Question", lms_question_name):
                    try:
                        other_usage = frappe.db.sql("""
                            SELECT parent
                            FROM `tabLMS Quiz Question`
                            WHERE question = %s AND parent != %s
                            LIMIT 1
                        """, (lms_question_name, assignment_doc.name))

                        if not other_usage:
                            frappe.delete_doc("LMS Question", lms_question_name, ignore_permissions=True)
                            lms_questions_deleted.append(lms_question_name)
                    except Exception as e:
                        frappe.log_error(
                            f"Failed to delete LMS Question {lms_question_name}: {str(e)}",
                            "LMS Question Deletion Error"
                        )

        # Save the updated assignment (if not already saved above)
        if not (data.get("type") == "Quiz/Multiple choice" and "quiz_questions" in data):
            assignment_doc.save(ignore_permissions=True)
            frappe.db.commit()

        return {
            "success": True,
            "message": "Assignment updated successfully",
            "data": {
                "assignment_name": assignment_doc.name,
                "title": assignment_doc.title,
                "type": assignment_doc.type,
                "due_date": str(assignment_doc.due_date) if assignment_doc.due_date else None,
                "recipients": {
                    "updated": recipients_updated,
                    "added": recipients_added,
                    "removed": recipients_removed,
                    "failed": recipients_failed,
                    "total_count": len(assignment_doc.recipient)
                },
                "quiz_questions": {
                    "lms_questions_created": lms_questions_created,
                    "lms_questions_updated": lms_questions_updated,
                    "lms_questions_deleted": lms_questions_deleted,
                    "quiz_questions_count": len(quiz_questions_updated)
                },
                "grade_assignment": bool(assignment_doc.grade_assignment),
                "show_answer": bool(assignment_doc.show_answer),
                "status": assignment_doc.status,
                "drafted": bool(assignment_doc.drafted),
                "public": bool(assignment_doc.public)
            }
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Assignment Update Failed")
        return {
            "success": False,
            "error": str(e),
            "traceback": frappe.get_traceback()
        }

@frappe.whitelist()
def get_assignment():
    """
    Get an existing assignment with all its details including quiz questions.
    """
    import json

    try:
        data = {}
        if frappe.request and frappe.request.data:
            data = json.loads(frappe.request.data)

        # Validate required field
        if not data.get("assignment_name"):
            return {"error": "Missing required field: assignment_name"}

        # Check if assignment exists
        if not frappe.db.exists("LMS Assignment", data.get("assignment_name")):
            return {"error": f"Assignment {data.get('assignment_name')} not found"}

        # Get the assignment
        assignment_doc = frappe.get_doc("LMS Assignment", data.get("assignment_name"))

        # Prepare recipients list
        recipients = []
        for recipient in assignment_doc.recipient:
            recipients.append({
                "students": recipient.students
            })

        # Prepare quiz questions list
        quiz_questions = []
        for quiz_q in assignment_doc.quiz_questions:
            # Get the linked LMS Question details if exists
            lms_question_details = {}
            if quiz_q.question and frappe.db.exists("LMS Question", quiz_q.question):
                lms_q_doc = frappe.get_doc("LMS Question", quiz_q.question)
                lms_question_details = {
                    "lms_question_name": lms_q_doc.name,
                    "question": lms_q_doc.question,
                    "type": lms_q_doc.type
                }

            quiz_questions.append({
                "lms_question_name": quiz_q.question,
                "question": lms_question_details.get("question", ""),
                "question_type": quiz_q.question_type,
                "option_a": quiz_q.option_a,
                "option_b": quiz_q.option_b,
                "option_c": quiz_q.option_c,
                "option_d": quiz_q.option_d,
                "correct_answer": quiz_q.correct_answer,
                "marks": quiz_q.marks,
                "points": quiz_q.points,
                "explanation": quiz_q.explanation
            })

        return {
            "success": True,
            "data": {
                "assignment_name": assignment_doc.name,
                "title": assignment_doc.title,
                "question": assignment_doc.question,
                "type": assignment_doc.type,
                "grade_assignment": bool(assignment_doc.grade_assignment),
                "show_answer": bool(assignment_doc.show_answer),
                "answer": assignment_doc.answer,
                "instructions": assignment_doc.instructions,
                "file": assignment_doc.file,
                "resource_link": assignment_doc.resource_link,
                "subject": assignment_doc.subject,
                "test_score": assignment_doc.test_score,
                "status": assignment_doc.status,
                "educational_level": assignment_doc.educational_level,
                "due_date": str(assignment_doc.due_date) if assignment_doc.due_date else None,
                "late_submission": bool(assignment_doc.late_submission),
                "set_reminders": bool(assignment_doc.set_reminders),
                "submitted": assignment_doc.submitted,
                "drafted": assignment_doc.drafted,
                "public": assignment_doc.public,
                "duration": assignment_doc.duration,
                "attempts_allowed": assignment_doc.attempts_allowed,
                "attempts_made":assignment_doc.attempts_made,
                "recipient": recipients,
                "quiz_questions": quiz_questions
            }
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Assignment Failed")
        return {
            "success": False,
            "error": str(e),
            "traceback": frappe.get_traceback()
        }

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
def get_all_student_assignment(user, limit=None, status_filter=None, **kwargs):
    """
    Fetch all assignments where a given student is in the recipient list.
    Status is fetched from LMS Assignment Student Status table.

    Args:
        status_filter: Optional filter - "Pending", "Overdue", "Submitted", "Pass", "Fail", "Graded"
    """
    from frappe.utils import get_datetime, now_datetime

    # Step 1: Find all LMS Assignment IDs linked to this student via student status
    student_status_records = frappe.get_all(
        "LMS Assignment Student Status",
        filters={"student": user},
        fields=["assignment", "status", "submission", "last_viewed"]
    )

    if not student_status_records:
        # If no status records exist, create them for existing assignments
        student_links = frappe.get_all(
            "PL Students",
            filters={"students": user},
            fields=["parent"],
        )

        if student_links:
            from lms.lms.doctype.lms_assignment_student_status.lms_assignment_student_status import create_student_status

            for link in student_links:
                # Create status record for each assignment
                create_student_status(link.parent, user)

            # Re-fetch after creating
            student_status_records = frappe.get_all(
                "LMS Assignment Student Status",
                filters={"student": user},
                fields=["assignment", "status", "submission", "last_viewed"]
            )

        if not student_status_records:
            return {
                "success": True,
                "message": "No assignments found for this student",
                "data": [],
                "count": 0,
            }

    assignment_ids = [s.get("assignment") for s in student_status_records]

    # Create a lookup for student status - FIXED: Use dict access
    status_lookup = {s.get("assignment"): s for s in student_status_records}

    # Step 2: Fetch the assignments
    filters = {"name": ["in", assignment_ids]}

    # Apply status filter if provided
    if status_filter:
        filtered_assignment_ids = [
            s.get("assignment") for s in student_status_records
            if (status_filter == "Graded" and s.get("status") in ["Pass", "Fail"]) or
               (status_filter != "Graded" and s.get("status") == status_filter)
        ]
        if not filtered_assignment_ids:
            return {
                "success": True,
                "message": f"No {status_filter} assignments found",
                "data": [],
                "count": 0,
            }
        filters["name"] = ["in", filtered_assignment_ids]

    filters.update(kwargs)

    user_assignments = frappe.get_all(
        "LMS Assignment",
        filters=filters,
        fields=["*"],
        limit=limit,
        order_by="creation desc",
    )

    result = []
    now = now_datetime()

    for a in user_assignments:
        # Get student status from lookup - FIXED: Use dict access
        student_status_record = status_lookup.get(a.get("name"))

        if not student_status_record:
            # This shouldn't happen, but just in case, create it
            from lms.lms.doctype.lms_assignment_student_status.lms_assignment_student_status import create_student_status
            create_student_status(a.get("name"), user)

            # Set default values
            student_status = "Pending"
            submission_id = None
        else:
            student_status = student_status_record.get("status")
            submission_id = student_status_record.get("submission")

        # Get submission details if exists
        student_score = None
        student_total_score = None
        has_submission = False

        if submission_id:
            submission = frappe.db.get_value(
                "LMS Assignment Submission",
                submission_id,
                ["score", "total_score"],
                as_dict=True
            )
            if submission:
                student_score = submission.get("score")
                student_total_score = submission.get("total_score")
                has_submission = True

        # Auto-update to Overdue if needed (and not yet submitted)
        if student_status == "Pending":
            due_date = a.get("due_date")
            if due_date and get_datetime(due_date) < now:
                # Update status to Overdue
                from lms.lms.doctype.lms_assignment_student_status.lms_assignment_student_status import update_student_status
                update_student_status(a.get("name"), user, "Overdue")
                student_status = "Overdue"

        # Count attempts for this student
        attempts_made = frappe.db.count(
            "LMS Assignment Submission",
            {"assignment": a.get("name"), "member": user}
        )

        # Get quiz questions
        quiz_questions = frappe.get_all(
            "LMS Quiz Question",
            filters={"parent": a.get("name"), "parenttype": "LMS Assignment"},
            fields=[
                "name", "question", "question_type", "marks",
                "option_a", "option_b", "option_c", "option_d",
                "correct_answer", "explanation", "duration", "selected_answer"
            ],
        )

        # Get LMS questions
        lms_questions = []
        for q in quiz_questions:
            if q.get("question"):
                lms_question_data = frappe.get_all(
                    "LMS Question",
                    filters={"name": q.get("question")},
                    fields=["name", "question", "is_correct_1", "is_correct_2", "is_correct_3", "is_correct_4"]
                )
                if lms_question_data:
                    lms_q = lms_question_data[0]
                    correct_option = "A"
                    if lms_q.get("is_correct_2"):
                        correct_option = "B"
                    elif lms_q.get("is_correct_3"):
                        correct_option = "C"
                    elif lms_q.get("is_correct_4"):
                        correct_option = "D"

                    lms_questions.append({
                        "name": lms_q.get("name"),
                        "question": lms_q.get("question"),
                        "correct_option": correct_option
                    })

        # Get instructor profile
        user_profile = frappe.get_all(
            "User Profile",
            filters={"user": a.get("owner")},
            fields=["*"],
        )

        instructor_user = frappe.get_doc(
            "User", user_profile[0].get("user") if user_profile else a.get("owner")
        )

        # Calculate attempts remaining
        attempts_remaining = a.get("attempts_allowed", 1) - attempts_made

        result.append({
            "id": a.get("name"),
            "title": a.get("title"),
            "type": a.get("type"),
            "question": a.get("question"),
            "created_at": a.get("creation"),
            "description": a.get("instructions") or a.get("description"),
            "file": a.get("file"),
            "resource_link": a.get("resource_link"),
            "show_answer": a.get("show_answer"),
            "due_date": a.get("due_date"),
            "total_marks": a.get("test_score"),
            "grade_assignment": a.get("grade_assignment"),
            "is_public": a.get("public"),
            "drafted": a.get("drafted"),
            "status": student_status,
            "has_submission": has_submission,
            "student_score": student_score,
            "student_total_score": student_total_score,
            "submission_id": submission_id,

            # Attempts tracking
            "attempts_allowed": a.get("attempts_allowed", 1),
            "attempts_made": attempts_made,
            "attempts_remaining": max(0, attempts_remaining),
            "can_submit": attempts_remaining > 0 and student_status not in ["Pass", "Fail"],

            "late_submission": a.get("late_submission"),
            "set_reminders": a.get("set_reminders"),
            "duration": a.get("duration"),
            "lms_questions": lms_questions,
            "quiz_questions": [
                {
                    "id": q.get("name"),
                    "question_id": q.get("question"),
                    "question_text": frappe.db.get_value("LMS Question", q.get("question"), "question") if q.get("question") else None,
                    "question_type": q.get("question_type"),
                    "marks": q.get("marks"),
                    "option_a": q.get("option_a"),
                    "option_b": q.get("option_b"),
                    "option_c": q.get("option_c"),
                    "option_d": q.get("option_d"),
                    "correct_answer": q.get("correct_answer"),
                    "explanation": q.get("explanation"),
                    "selected_answer": q.get("selected_answer")
                }
                for q in quiz_questions
            ],
            "subject": (
                {
                    "id": a.get("subject"),
                    "subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
                }
                if a.get("subject") else None
            ),
            "educational_level": (
                {
                    "id": a.get("educational_level"),
                    "educational_level": frappe.db.get_value(
                        "LMS Course Level", a.get("educational_level"), "education_level"
                    ),
                }
                if a.get("educational_level") else None
            ),
            "instructor": {
                "full_name": instructor_user.full_name,
                "email": user_profile[0].get("user") if user_profile else a.get("owner"),
                "bio": user_profile[0].get("bio") if user_profile else "",
                "profile_image": user_profile[0].get("profile_image") if user_profile else "",
            },
        })

    return {
        "success": True,
        "message": "Assignments fetched successfully",
        "data": result,
        "count": len(result),
    }

@frappe.whitelist()
def get_all_instructor_assignment(user, limit=None, **kwargs):
    """
    Fetch all assignments created by a given instructor.
    """
    # Build filters and fetch assignments
    filters = {"owner": user}
    filters.update(kwargs or {})
    instructor_assignments = frappe.get_all(
        "LMS Assignment",
        filters=filters,
        fields=["*"],
        limit=limit,
        order_by="creation desc",
    )

    if not instructor_assignments:
        return {
            "success": True,
            "message": "No assignments found for this instructor",
            "data": [],
            "count": 0,
        }

    result = []
    for a in instructor_assignments:
        # Fetch quiz questions belonging to this assignment
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
                "duration",
                "selected_answer"
            ],
        )

        # Build lms_questions list by resolving referenced LMS Question docs
        lms_questions = []
        for q in quiz_questions:
            if q.get("question"):
                lms_question_data = frappe.get_all(
                    "LMS Question",
                    filters={"name": q.get("question")},
                    fields=["name", "question", "is_correct_1", "is_correct_2", "is_correct_3", "is_correct_4"],
                )
                if lms_question_data:
                    lms_q = lms_question_data[0]
                    # Determine correct option based on is_correct flags
                    correct_option = "A"
                    if lms_q.get("is_correct_2"):
                        correct_option = "B"
                    elif lms_q.get("is_correct_3"):
                        correct_option = "C"
                    elif lms_q.get("is_correct_4"):
                        correct_option = "D"

                    lms_questions.append({
                        "name": lms_q.get("name"),
                        "question": lms_q.get("question"),
                        "correct_option": correct_option,
                    })

        recipients = frappe.db.sql(
            """
            SELECT students as `student`
            FROM `tabPL Students`
            WHERE parent = %(assignment)s
            ORDER BY idx
            """,
            {"assignment": a.get("name")},
            as_dict=True,
        )


        recipients_list = []
        for r in recipients:
            student_email = r.get("student")
            user_doc = None
            profile = None

            try:
                if frappe.db.exists("User", student_email):
                    user_doc = frappe.get_doc("User", student_email)
            except Exception:
                user_doc = None

            try:
                ups = frappe.get_all(
                    "User Profile",
                    filters={"user": student_email},
                    fields=["bio", "user_image", "user_image"]
                )
                profile = ups[0] if ups else None
            except Exception:
                profile = None

            profile_image = ""
            if profile:
                profile_image = profile.get("user_image") or profile.get("user_image") or ""

            recipients_list.append({
                "full_name": user_doc.full_name if user_doc and getattr(user_doc, "full_name", None) else student_email,
                "email": student_email,
                "profile_image": profile_image,
                "bio": profile.get("bio") if profile else ""
            })

        # Instructor profile (if exists)
        user_profile = frappe.get_all(
            "User Profile",
            filters={"user": user},
            fields=["*"],
        )
        instructor_user = frappe.get_doc("User", user)

        result.append({
            "id": a.get("name"),
            "title": a.get("title"),
            "type": a.get("type"),
            "question": a.get("question"),
            "created_at": a.get("creation"),
            "description": a.get("instructions") or a.get("description"),
            "file": a.get("file"),
            "resource_link": a.get("resource_link"),
            "show_answer": a.get("show_answer"),
            "due_date": a.get("due_date"),
            "total_marks": a.get("test_score"),
            "submitted": a.get("submitted"),
            "drafted": a.get("drafted"),
            "grade_assignment": a.get("grade_assignment"),
            "is_public": a.get("public"),
            "status": a.get("status"),
            "late_submission": a.get("late_submission"),
            "set_reminders": a.get("set_reminders"),
            "attempts_allowed": a.get("attempts_allowed"),
            "attempts_made": a.get("attempts_made"),
            "duration": a.get("duration"),
            "recipients": recipients_list,
            "lms_questions": lms_questions,
            "quiz_questions": [
    {
        "id": q.get("name"),
        "question_id": q.get("question"),
        "question_text": frappe.db.get_value("LMS Question", q.get("question"), "question") if q.get("question") else None,
        "question_type": q.get("question_type"),
        "marks": q.get("marks"),
        "option_a": q.get("option_a"),
        "option_b": q.get("option_b"),
        "option_c": q.get("option_c"),
        "option_d": q.get("option_d"),
        "correct_answer": q.get("correct_answer"),
        "explanation": q.get("explanation"),
        "selected_answer": q.get("selected_answer"),
    }
    for q in quiz_questions
],

            "subject": (
                {
                    "id": a.get("subject"),
                    "subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
                } if a.get("subject") else None
            ),
            "educational_level": (
                {
                    "id": a.get("educational_level"),
                    "educational_level": frappe.db.get_value(
                        "LMS Course Level", a.get("educational_level"), "education_level"
                    ),
                } if a.get("educational_level") else None
            ),
            "instructor": {
                "full_name": instructor_user.full_name,
                "email": user,
                "bio": user_profile[0].get("bio") if user_profile else "",
                "profile_image": user_profile[0].get("user_image") if user_profile else "",
            },
        })

    return {
        "success": True,
        "message": "Assignments fetched successfully",
        "data": result,
        "count": len(result),
    }

@frappe.whitelist(allow_guest=True)
def get_assignment_details(assignment):
    """
    Fetch detailed information about a specific assignment.
    """
    assignments = frappe.get_all(
        "LMS Assignment",
        filters={"name": assignment},
        fields=["*"],
    )

    if not assignments:
        return {
            "success": False,
            "message": "Assignment not found",
            "data": None,
            "count": 0,
        }

    a = assignments[0]

    # Quiz questions
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
            "selected_answer"
        ],
    )

    # Build lms_questions the same way as other endpoints
    lms_questions = []
    for q in quiz_questions:
        if q.get("question"):
            lms_question_data = frappe.get_all(
                "LMS Question",
                filters={"name": q.get("question")},
                fields=["name", "question", "is_correct_1", "is_correct_2", "is_correct_3", "is_correct_4"],
            )
            if lms_question_data:
                lms_q = lms_question_data[0]
                correct_option = "A"
                if lms_q.get("is_correct_2"):
                    correct_option = "B"
                elif lms_q.get("is_correct_3"):
                    correct_option = "C"
                elif lms_q.get("is_correct_4"):
                    correct_option = "D"

                lms_questions.append({
                    "name": lms_q.get("name"),
                    "question": lms_q.get("question"),
                    "correct_option": correct_option,
                })

    # Recipients (students)
    recipients = frappe.db.sql(
        """
        SELECT students as `student`
        FROM `tabPL Students`
        WHERE parent = %(assignment)s
        ORDER BY idx
        """,
        {"assignment": assignment},
        as_dict=True,
    )

    recipients_list = []
    for r in recipients:
            student_email = r.get("student")
            user_doc = None
            profile = None

            try:
                if frappe.db.exists("User", student_email):
                    user_doc = frappe.get_doc("User", student_email)
            except Exception:
                user_doc = None

            try:
                ups = frappe.get_all(
                    "User Profile",
                    filters={"user": student_email},
                    fields=["bio", "user_image", "user_image"]
                )
                profile = ups[0] if ups else None
            except Exception:
                profile = None

            profile_image = ""
            if profile:
                profile_image = profile.get("user_image") or profile.get("user_image") or ""

            recipients_list.append({
                "full_name": user_doc.full_name if user_doc and getattr(user_doc, "full_name", None) else student_email,
                "email": student_email,
                "profile_image": profile_image,
                "bio": profile.get("bio") if profile else ""
            })

    # Instructor profile (if exists)
    user_profile = frappe.get_all(
        "User Profile",
        filters={"user": a.get("owner")},
        fields=["*"],
    )
    instructor_user = frappe.get_doc(
        "User", user_profile[0].get("user") if user_profile else a.get("owner")
    )

    result = {
        "id": a.get("name"),
        "title": a.get("title"),
        "type": a.get("type"),
        "question": a.get("question"),
        "created_at": a.get("creation"),
        "description": a.get("instructions") or a.get("description"),
        "file": a.get("file"),
        "resource_link": a.get("resource_link"),
        "show_answer": a.get("show_answer"),
        "due_date": a.get("due_date"),
        "total_marks": a.get("test_score"),
        "submitted": a.get("submitted"),
        "drafted": a.get("drafted"),
        "grade_assignment": a.get("grade_assignment"),
        "is_public": a.get("public"),
        "status": a.get("status"),
        "recipients": recipients_list,
        "late_submission": a.get("late_submission"),
        "set_reminders": a.get("set_reminders"),
        "attempts_allowed": a.get("attempts_allowed"),
        "duration": a.get("duration"),
        "attempts_made": a.get("attempts_made"),
        "lms_questions": lms_questions,
        "quiz_questions": [
    {
        "id": q.get("name"),
        "question_id": q.get("question"),
        "question_text": frappe.db.get_value("LMS Question", q.get("question"), "question") if q.get("question") else None,
        "question_type": q.get("question_type"),
        "marks": q.get("marks"),
        "option_a": q.get("option_a"),
        "option_b": q.get("option_b"),
        "option_c": q.get("option_c"),
        "option_d": q.get("option_d"),
        "correct_answer": q.get("correct_answer"),
        "explanation": q.get("explanation"),
        "selected_answer": q.get("selected_answer"),
    }
    for q in quiz_questions
],

        "subject": (
            {
                "id": a.get("subject"),
                "subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
            } if a.get("subject") else None
        ),
        "educational_level": (
            {
                "id": a.get("educational_level"),
                "educational_level": frappe.db.get_value(
                    "LMS Course Level", a.get("educational_level"), "education_level"
                ),
            } if a.get("educational_level") else None
        ),
        "instructor": {
            "full_name": instructor_user.full_name,
            "email": user_profile[0].get("user") if user_profile else a.get("owner"),
            "bio": user_profile[0].get("bio") if user_profile else "",
            "profile_image": user_profile[0].get("user_image") if user_profile else "",
        },
    }

    return {
        "success": True,
        "message": "Assignment fetched successfully",
        "data": result,
        "count": 1,
    }

@frappe.whitelist()
def get_overdue_assignments(student):
    """
    Fetch all assignments that are overdue for a specific student using student status.
    """
    try:
        from frappe.utils import now_datetime, get_datetime
        
        # Get overdue assignments from student status table
        overdue_status_records = frappe.get_all(
            "LMS Assignment Student Status",
            filters={
                "student": student,
                "status": "Overdue"
            },
            fields=["assignment"]
        )

        if not overdue_status_records:
            return {
                "success": True,
                "message": "No overdue assignments found",
                "data": [],
                "count": 0,
            }

        assignment_ids = [s.assignment for s in overdue_status_records]

        # Fetch assignment details
        overdue_assignments = frappe.get_all(
            "LMS Assignment",
            filters={"name": ["in", assignment_ids]},
            fields=["*"],
            order_by="due_date asc",
        )

        # Filter assignments to only include those whose due_date has actually passed
        now = now_datetime()
        result = []
        for a in overdue_assignments:
            # Check if due_date has actually passed
            due_date = a.get("due_date")
            if not due_date or get_datetime(due_date) >= now:
                # Skip this assignment - due date hasn't passed or doesn't exist
                continue
                
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
                    "duration",
                    "selected_answer"
                ],
            )

            user_profile = frappe.get_all(
                "User Profile",
                filters={"user": a.get("owner")},
                fields=["*"],
            )

            instructor_user = frappe.get_doc(
                "User", user_profile[0].get("user") if user_profile else a.get("owner")
            )

            result.append({
                "id": a.get("name"),
                "title": a.get("title"),
                "type": a.get("type"),
                "question": a.get("question"),
                "created_at": a.get("creation"),
                "description": a.get("instructions"),
                "file": a.get("file"),
                "resource_link": a.get("resource_link"),
                "show_answer": a.get("show_answer"),
                "due_date": a.get("due_date"),
                "total_marks": a.get("test_score"),
                "submitted": a.get("submitted"),
                "drafted": a.get("drafted"),
                "grade_assignment": a.get("grade_assignment"),
                "is_public": a.get("public"),
                "status": "Overdue",
                "late_submission": a.get("late_submission"),
                "set_reminders": a.get("set_reminders"),
                "attempts_allowed": a.get("attempts_allowed"),
                "quiz_questions": [
    {
        "id": q.get("name"),
        "question_id": q.get("question"),
        "question_text": frappe.db.get_value("LMS Question", q.get("question"), "question") if q.get("question") else None,
        "question_type": q.get("question_type"),
        "marks": q.get("marks"),
        "option_a": q.get("option_a"),
        "option_b": q.get("option_b"),
        "option_c": q.get("option_c"),
        "option_d": q.get("option_d"),
        "correct_answer": q.get("correct_answer"),
        "explanation": q.get("explanation"),
        "duration": q.get("duration"),
        "selected_answer": q.get("selected_answer"),
    }
    for q in quiz_questions
],

                "subject": (
                    {
                        "id": a.get("subject"),
                        "subject_name": frappe.db.get_value(
                            "Subject", a.get("subject"), "subject_name"
                        ),
                    }
                    if a.get("subject")
                    else None
                ),
                "educational_level": (
                    {
                        "id": a.get("educational_level"),
                        "educational_level": frappe.db.get_value(
                            "LMS Course Level",
                            a.get("educational_level"),
                            "education_level",
                        ),
                    }
                    if a.get("educational_level")
                    else None
                ),
                "instructor": {
                    "full_name": instructor_user.full_name,
                    "email": user_profile[0].get("user") if user_profile else a.get("owner"),
                    "bio": user_profile[0].get("bio") if user_profile else "",
                    "profile_image": user_profile[0].get("profile_image") if user_profile else "",
                },
            })

        return {
            "success": True,
            "message": "Overdue assignments fetched successfully",
            "data": result,
            "count": len(result),
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Overdue Assignments Failed")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def mark_overdue_assignments():
    """Scheduled job: mark all LMS Assignment records whose due_date has passed as Overdue."""
    try:
        from frappe.utils import nowdate

        today = nowdate()

        # fetch assignments with due_date before today and not already Overdue/Graded
        assignments = frappe.get_all(
            "LMS Assignment",
            filters=[
                ["due_date", "<", today],
                ["status", "not in", ["Overdue", "Graded"]]
            ],
            fields=["name"],
        )

        updated = 0
        for a in assignments:
            try:
                frappe.db.set_value("LMS Assignment", a.name, "status", "Overdue", update_modified=False)
                updated += 1
            except Exception as inner_e:
                frappe.log_error(f"Failed to mark {a.name} Overdue: {inner_e}", "Mark Overdue Error")

        frappe.db.commit()
        return {"updated": updated}
    except Exception as e:
        frappe.log_error(f"mark_overdue_assignments: {e}", "Mark Overdue Scheduler Error")
        return {"updated": 0, "error": str(e)}
