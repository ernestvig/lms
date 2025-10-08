# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class LMSCourseReview(Document):
	def validate(self):
		self.validate_if_already_reviewed()

	def validate_if_already_reviewed(self):
		if frappe.db.exists("LMS Course Review", {"course": self.course, "owner": self.owner}):
			frappe.throw(frappe._("You have already reviewed this course"))


@frappe.whitelist()
def submit_review(rating, review, course, anonymous=0):
    try:
        # Validate course exists
        if not frappe.db.exists("LMS Course", course):
            frappe.throw("Course not found")

        # Get max rating value (default 5)
        out_of_ratings = 5  # Default value
        try:
            rating_field = frappe.get_meta("LMS Course Review").get_field("rating")
            if rating_field and rating_field.options:
                out_of_ratings = cint(rating_field.options)
        except Exception:
            pass  # Use default if field meta can't be retrieved

        # Create review
        rating = cint(rating)
        anonymous = cint(anonymous)

        review_doc = frappe.get_doc({
            "doctype": "LMS Course Review",
            "rating": rating,
            "review": review,
            "course": course,
            "anonymous": anonymous
        })
        review_doc.save(ignore_permissions=True)

        # Recalc average rating
        all_reviews = frappe.get_all(
            "LMS Course Review",
            filters={"course": course},
            fields=["rating"]
        )

        avg_rating = 0
        if all_reviews:
            avg_rating = sum([r["rating"] for r in all_reviews]) / len(all_reviews)
            frappe.db.set_value("LMS Course", course, "rating", avg_rating)

        # Get user full name correctly
        user_full_name = frappe.db.get_value("User", review_doc.owner, "full_name")

        return {
            "status": "OK",
            "message": "Review submitted successfully",
            "data": {
                "out_of_ratings": out_of_ratings,
                "average_rating": avg_rating,
                "total_reviews": len(all_reviews),
                "your_review": {
                    "rating": rating,
                    "review": review,
                    "anonymous": anonymous,
                    "owner": user_full_name or review_doc.owner,
                    "creation": review_doc.creation,
                },
            },
        }

    except frappe.exceptions.ValidationError as e:
        frappe.log_error(frappe.get_traceback(), "Review Submission Error")
        return {
            "status": "ERROR",
            "message": str(e)
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Review Submission Error")
        return {
            "status": "ERROR",
            "message": "An error occurred while submitting the review"
        }
