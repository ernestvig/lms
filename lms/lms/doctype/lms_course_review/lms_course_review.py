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
def submit_review(rating, review, course):
    # max rating value (default 5)
    out_of_ratings = frappe.db.get_all(
        "DocField", {"parent": "LMS Course Review", "fieldtype": "Rating"}, ["options"]
    )
    out_of_ratings = (len(out_of_ratings) and cint(out_of_ratings[0].options)) or 5.0

    # create review
    rating = float(rating)
    out_of_ratings = float(out_of_ratings)
    
    if rating < 1 or rating > out_of_ratings:
        frappe.throw(f"Rating must be between 1 and {out_of_ratings}")
    
    normalized_rating = rating / out_of_ratings
    # return normalized_rating, rating, out_of_ratings
        
    review_doc = frappe.get_doc(
        {"doctype": "LMS Course Review", "rating": normalized_rating, "review": review, "course": course}
    )
    review_doc.save(ignore_permissions=True)

    # recalc average rating
    all_reviews = frappe.get_all("LMS Course Review", filters={"course": course}, fields=["rating"])
    avg_rating = 0
    if all_reviews:
        avg_rating = sum([r["rating"] for r in all_reviews]) / len(all_reviews)
        frappe.db.set_value("LMS Course", course, "rating", avg_rating)

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
                "owner": frappe.db.get_value("User", {"name": review_doc.owner}, "full_name"),
                "creation": review_doc.creation,
            },
        },
    }
