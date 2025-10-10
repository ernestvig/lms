# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt
from dataclasses import fields

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import ceil
from lms.lms.utils import get_course_progress


class LMSEnrollment(Document):
	def validate(self):
		self.validate_membership_in_same_batch()
		self.validate_membership_in_different_batch_same_course()

	def on_update(self):
		update_program_progress(self.member)

	def validate_membership_in_same_batch(self):
		filters = {"member": self.member, "course": self.course, "name": ["!=", self.name]}
		if self.batch_old:
			filters["batch_old"] = self.batch_old
		previous_membership = frappe.db.get_value(
			"LMS Enrollment", filters, fieldname=["member_type", "member"], as_dict=1
		)

		if previous_membership:
			member_name = frappe.db.get_value("User", self.member, "full_name")
			course_title = frappe.db.get_value("LMS Course", self.course, "title")
			frappe.throw(
				_("{0} is already a {1} of the course {2}").format(
					member_name, previous_membership.member_type, course_title
				)
			)

	def validate_membership_in_different_batch_same_course(self):
		"""Ensures that a studnet is only part of one batch."""
		# nothing to worry if the member is not a student
		if self.member_type != "Student":
			return

		course = frappe.db.get_value("LMS Batch Old", self.batch_old, "course")
		memberships = frappe.get_all(
			"LMS Enrollment",
			filters={
				"member": self.member,
				"name": ["!=", self.name],
				"member_type": "Student",
				"course": self.course,
			},
			fields=["batch_old", "member_type", "name"],
		)

		if memberships:
			membership = memberships[0]
			member_name = frappe.db.get_value("User", self.member, "full_name")
			frappe.throw(
				_("{0} is already a Student of {1} course through {2} batch").format(
					member_name, course, membership.batch_old
				)
			)


def update_program_progress(member):
	programs = frappe.get_all("LMS Program Member", {"member": member}, ["parent", "name"])

	for program in programs:
		total_progress = 0
		courses = frappe.get_all("LMS Program Course", {"parent": program.parent}, pluck="course")
		for course in courses:
			progress = frappe.db.get_value("LMS Enrollment", {"course": course, "member": member}, "progress")
			progress = progress or 0
			total_progress += progress

		average_progress = ceil(total_progress / len(courses))
		frappe.db.set_value("LMS Program Member", program.name, "progress", average_progress)


@frappe.whitelist()
def create_membership(course, batch=None, member=None, member_type="Student", role="Member"):
	if frappe.db.get_value("LMS Course", course, "disable_self_learning"):
		return False

	enrollment = frappe.new_doc("LMS Enrollment")
	enrollment.update(
		{
			"doctype": "LMS Enrollment",
			"batch_old": batch,
			"course": course,
			"role": role,
			"member_type": member_type,
			"member": member or frappe.session.user,
		}
	)
	enrollment.insert()
	return enrollment


@frappe.whitelist()
def update_current_membership(batch, course, member):
	all_memberships = frappe.get_all("LMS Enrollment", {"member": member, "course": course})
	for membership in all_memberships:
		frappe.db.set_value("LMS Enrollment", membership.name, "is_current", 0)

	current_membership = frappe.get_all("LMS Enrollment", {"batch_old": batch, "member": member})
	if len(current_membership):
		frappe.db.set_value("LMS Enrollment", current_membership[0].name, "is_current", 1)


@frappe.whitelist(allow_guest=True)
def get_student_enrollments(student=None, limit=None, start=0, status=None):
	"""
	Get student enrollments with transformed response format

	Args:
		student: Student email (defaults to current user)
		limit: Number of records to fetch
		start: Starting index for pagination
		status: Filter by course status ('ongoing', 'complete', 'cancelled')
	"""
	student = student or frappe.session.user
	if not student:
		return {
			"success": False,
			"message": "Student not found"
		}

	# Build filters
	filters = {
		"member": student,
		"member_type": "Student"
	}

	# Add status filter if provided
	if status:
		# Map status values if needed (the status is on the LMS Course doctype)
		# We'll need to join with course to filter by status
		pass  # We'll handle this in the query below

	# Get enrollments
	enrollments = frappe.get_all(
		"LMS Enrollment",
		filters=filters,
		fields=["*"],
		limit=limit,
		start=start,
		order_by="creation desc",
	)

	# Transform the response
	transformed_courses = []

	for enrollment in enrollments:
		# Get course details
		course = frappe.get_doc("LMS Course", enrollment.course)

		# Skip if status filter is applied and doesn't match
		if status and course.status.lower() != status.lower():
			continue

		# Get chapter count (modules)
		chapter_count = frappe.db.count(
			"Chapter Reference",
			{"parent": course.name}
		)

		# Get instructor name (first instructor)
		instructor_name = "Unknown"
		if course.instructors and len(course.instructors) > 0:
			instructor = frappe.get_doc("User", course.instructors[0].instructor)
			instructor_name = instructor.full_name or instructor.name

		# Calculate duration from lessons
		total_duration_minutes = 0
		chapters = frappe.get_all(
			"Chapter Reference",
			filters={"parent": course.name},
			fields=["chapter"]
		)

		for chapter in chapters:
			lessons = frappe.get_all(
				"Lesson Reference",
				filters={"parent": chapter.chapter},
				fields=["lesson"]
			)
			# You might want to add a duration field to lessons
			# For now, assuming average 15 mins per lesson
			total_duration_minutes += len(lessons) * 15

		# Format duration
		hours = total_duration_minutes // 60
		minutes = total_duration_minutes % 60
		duration = f"{hours} hours {minutes} mins" if hours > 0 else f"{minutes} mins"

		# Build transformed course object
		course_progress = get_course_progress(course.name, frappe.session.user)
		course_status = "Complete" if course_progress == 100 else "Ongoing"

		transformed_course = {
			"id": course.name,
			"slug": course.name,
			"title": course.title,
			"tutor": instructor_name,
			"tutorId": course.instructors[0].instructor if course.instructors else None,
			"thumbnail_image": course.image ,
			"enrolled": course.enrollments or 0,
			"modules": chapter_count,
			"status": course_status,
			"percentage_complete": enrollment.progress or 0,
			"duration": duration
		}

		transformed_courses.append(transformed_course)

	# Count after filtering
	filtered_count = len(transformed_courses)

	return {
		"success": True,
		"data": {
			"courses": transformed_courses
		},
		"message": "Enrolled courses retrieved successfully"
	}

@frappe.whitelist()
def get_tutor_enrollment_kpi(tutor):
    # Get courses where the tutor is an instructor
    # Check in the Course Instructor child table
    course_instructors = frappe.get_all(
        "Course Instructor",
        filters={"instructor": tutor},
        fields=["parent"],
    )

    # Extract unique course names
    course_names_list = list(set([ci.parent for ci in course_instructors]))
    course_count = len(course_names_list)

    if not course_names_list:
        return {
            "success": True,
            "course_count": 0,
            "student_enrollment_count": 0,
            "completion_rate": "0%",
        }

    # Get total student enrollments across tutor's courses
    enrollments = frappe.get_all(
        "LMS Enrollment",
        filters={
            "course": ["in", course_names_list],
            "member_type": "Student"
        },
        fields=["progress"],
    )

    student_enrollment_count = len(enrollments)

    if student_enrollment_count == 0:
        return {
            "success": True,
            "course_count": course_count,
            "student_enrollment_count": 0,
            "completion_rate": "0%",
        }

    # Calculate completion rate
    completed_count = 0
    for enrollment in enrollments:
        progress = enrollment.progress or 0
        # Consider completed if progress is 100%
        if progress >= 100:
            completed_count += 1

    # Calculate completion rate percentage
    completion_rate = round((completed_count / student_enrollment_count) * 100, 2)

    return {
        "success": True,
        "course_count": course_count,
        "student_enrollment_count": student_enrollment_count,
        "completion_rate": f"{completion_rate}%",
    }
