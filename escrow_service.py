"""
Escrow Service Module

This module handles the complete escrow payment flow:
1. Buyer pays to business account (STK Push via Pesapal)
2. System maps payment to seller/product
3. Money held until buyer confirms receipt
4. On confirmation, money released to seller's phone number
"""

from datetime import datetime, timedelta
from bson import ObjectId
from payment import (
    initiate_pesapal_payment,
    check_pesapal_payment_status,
    send_money_via_at,
    format_phone_number
)


class EscrowService:
    """Handles all escrow-related operations"""

    # Escrow statuses
    STATUS_PENDING = "pending"          # Payment initiated, waiting for buyer payment
    STATUS_PAID = "paid"                # Buyer has paid, money held in escrow
    STATUS_CONFIRMED = "confirmed"      # Buyer confirmed receipt
    STATUS_RELEASED = "released"        # Money released to seller
    STATUS_DISPUTED = "disputed"        # Buyer raised a dispute
    STATUS_REFUNDED = "refunded"        # Money refunded to buyer
    STATUS_CANCELLED = "cancelled"      # Transaction cancelled
    STATUS_EXPIRED = "expired"          # Payment window expired

    # Time limits
    PAYMENT_EXPIRY_HOURS = 24           # Hours before pending payment expires
    CONFIRMATION_DAYS = 7               # Days buyer has to confirm before auto-release
    DISPUTE_WINDOW_DAYS = 3             # Days after delivery to raise dispute

    def __init__(self, db):
        """Initialize with database connection"""
        self.db = db
        self.escrow_collection = db.escrow_payments
        self.products_collection = db.products

    def create_escrow_payment(self, product_id, buyer_phone, buyer_name=None):
        """
        Create a new escrow payment for a product purchase.

        Args:
            product_id: ID of the product being purchased
            buyer_phone: Buyer's phone number
            buyer_name: Optional buyer name

        Returns:
            dict with escrow_id, payment_url, and amount on success
            dict with error on failure
        """
        try:
            # Get product details
            product = self.products_collection.find_one({"_id": ObjectId(product_id)})
            if not product:
                return {"success": False, "error": "Product not found"}

            # Check product availability
            if product.get("sold", False):
                return {"success": False, "error": "Product has already been sold"}

            if product.get("status") == "reserved":
                # Check if reservation has expired
                existing_escrow = self.escrow_collection.find_one({
                    "product_id": product_id,
                    "status": {"$in": [self.STATUS_PENDING, self.STATUS_PAID]}
                })
                if existing_escrow:
                    # Check if payment expired
                    created_at = existing_escrow.get("created_at")
                    if created_at:
                        expiry_time = created_at + timedelta(hours=self.PAYMENT_EXPIRY_HOURS)
                        if datetime.utcnow() < expiry_time:
                            return {"success": False, "error": "Product is currently reserved by another buyer"}
                        else:
                            # Expire the old escrow
                            self._expire_escrow(existing_escrow["_id"])

            # Format buyer phone
            buyer_phone = format_phone_number(buyer_phone)

            # Get seller info from product
            seller_number = product.get("user_number")
            seller_phone = product.get("contact") or seller_number

            # Get payment amount
            amount = float(product.get("selling_price", 0))
            if amount <= 0:
                return {"success": False, "error": "Invalid product price"}

            # Create escrow record
            escrow_payment = {
                "product_id": product_id,
                "seller_number": seller_number,
                "seller_phone": format_phone_number(seller_phone),
                "buyer_phone": buyer_phone,
                "buyer_name": buyer_name,
                "amount": amount,
                "description": f"Purchase of: {product.get('description', 'Item')[:100]}",
                "product_description": product.get("description"),
                "product_category": product.get("category"),
                "status": self.STATUS_PENDING,
                "created_at": datetime.utcnow(),
                "payment_expiry": datetime.utcnow() + timedelta(hours=self.PAYMENT_EXPIRY_HOURS),
                "history": [{
                    "status": self.STATUS_PENDING,
                    "timestamp": datetime.utcnow(),
                    "note": "Escrow payment created"
                }]
            }

            # Insert escrow record
            result = self.escrow_collection.insert_one(escrow_payment)
            escrow_id = str(result.inserted_id)

            # Initiate Pesapal payment (STK Push)
            payment_result = initiate_pesapal_payment(
                amount,
                buyer_phone,
                f"Escrow: {product.get('description', 'Item')[:50]}"
            )

            if payment_result and payment_result.get('redirect_url'):
                # Update escrow with payment tracking info
                self.escrow_collection.update_one(
                    {"_id": result.inserted_id},
                    {"$set": {
                        "order_tracking_id": payment_result.get('order_tracking_id'),
                        "merchant_reference": payment_result.get('merchant_reference'),
                        "payment_url": payment_result.get('redirect_url')
                    }}
                )

                # Reserve the product
                self.products_collection.update_one(
                    {"_id": ObjectId(product_id)},
                    {"$set": {
                        "status": "reserved",
                        "reserved_by": escrow_id,
                        "reserved_at": datetime.utcnow()
                    }}
                )

                return {
                    "success": True,
                    "data": {
                        "escrow_id": escrow_id,
                        "payment_url": payment_result['redirect_url'],
                        "amount": amount,
                        "currency": "KES",
                        "seller_phone": seller_phone,
                        "product_description": product.get("description"),
                        "payment_expiry": (datetime.utcnow() + timedelta(hours=self.PAYMENT_EXPIRY_HOURS)).isoformat()
                    }
                }
            else:
                # Clean up on failure
                self.escrow_collection.delete_one({"_id": result.inserted_id})
                return {"success": False, "error": "Payment initiation failed"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def handle_payment_callback(self, order_tracking_id, payment_status_data):
        """
        Handle payment callback from Pesapal.
        Called when buyer completes payment.

        Args:
            order_tracking_id: Pesapal order tracking ID
            payment_status_data: Payment status data from Pesapal

        Returns:
            dict with success status and escrow details
        """
        try:
            # Find the escrow payment
            escrow = self.escrow_collection.find_one({"order_tracking_id": order_tracking_id})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            payment_status = payment_status_data.get('payment_status_description', '')

            if payment_status == 'Completed':
                # Update escrow to paid status
                self.escrow_collection.update_one(
                    {"_id": escrow["_id"]},
                    {
                        "$set": {
                            "status": self.STATUS_PAID,
                            "paid_at": datetime.utcnow(),
                            "payment_details": payment_status_data,
                            "confirmation_deadline": datetime.utcnow() + timedelta(days=self.CONFIRMATION_DAYS)
                        },
                        "$push": {
                            "history": {
                                "status": self.STATUS_PAID,
                                "timestamp": datetime.utcnow(),
                                "note": "Payment received, funds held in escrow"
                            }
                        }
                    }
                )

                return {
                    "success": True,
                    "escrow_id": str(escrow["_id"]),
                    "status": self.STATUS_PAID,
                    "message": "Payment received and held in escrow"
                }

            elif payment_status in ['Failed', 'Invalid']:
                # Update escrow to cancelled
                self._cancel_escrow(escrow["_id"], "Payment failed")
                return {
                    "success": False,
                    "escrow_id": str(escrow["_id"]),
                    "status": self.STATUS_CANCELLED,
                    "error": "Payment failed"
                }

            return {"success": True, "message": "Payment status pending"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def confirm_receipt(self, escrow_id, buyer_phone):
        """
        Buyer confirms they received the item.
        This triggers release of funds to seller.

        Args:
            escrow_id: ID of the escrow payment
            buyer_phone: Buyer's phone number (for verification)

        Returns:
            dict with success status and payout details
        """
        try:
            escrow = self.escrow_collection.find_one({"_id": ObjectId(escrow_id)})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            # Verify buyer
            formatted_buyer_phone = format_phone_number(buyer_phone)
            if escrow.get("buyer_phone") != formatted_buyer_phone:
                return {"success": False, "error": "Unauthorized: Phone number does not match"}

            # Check status
            if escrow.get("status") != self.STATUS_PAID:
                return {"success": False, "error": f"Cannot confirm: Escrow status is '{escrow.get('status')}'"}

            # Update to confirmed
            self.escrow_collection.update_one(
                {"_id": ObjectId(escrow_id)},
                {
                    "$set": {
                        "status": self.STATUS_CONFIRMED,
                        "confirmed_at": datetime.utcnow()
                    },
                    "$push": {
                        "history": {
                            "status": self.STATUS_CONFIRMED,
                            "timestamp": datetime.utcnow(),
                            "note": "Buyer confirmed receipt of item"
                        }
                    }
                }
            )

            # Release funds to seller
            return self.release_funds(escrow_id)

        except Exception as e:
            return {"success": False, "error": str(e)}

    def release_funds(self, escrow_id):
        """
        Release escrowed funds to seller.

        Args:
            escrow_id: ID of the escrow payment

        Returns:
            dict with success status and transaction details
        """
        try:
            escrow = self.escrow_collection.find_one({"_id": ObjectId(escrow_id)})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            # Check if already released
            if escrow.get("status") == self.STATUS_RELEASED:
                return {"success": False, "error": "Funds have already been released"}

            # Check valid status for release
            if escrow.get("status") not in [self.STATUS_PAID, self.STATUS_CONFIRMED]:
                return {"success": False, "error": f"Cannot release: Escrow status is '{escrow.get('status')}'"}

            # Get seller phone and amount
            seller_phone = escrow.get("seller_phone") or escrow.get("seller_number")
            amount = escrow.get("amount")

            # Send money to seller via Africa's Talking
            payout_result = send_money_via_at(
                seller_phone,
                amount,
                f"Sale payment: {escrow.get('description', 'Item sale')[:50]}"
            )

            if payout_result and payout_result.get("status") == "success":
                # Update escrow to released
                self.escrow_collection.update_one(
                    {"_id": ObjectId(escrow_id)},
                    {
                        "$set": {
                            "status": self.STATUS_RELEASED,
                            "released_at": datetime.utcnow(),
                            "payout_reference": payout_result.get("data", {}).get("transactionId"),
                            "payout_details": payout_result
                        },
                        "$push": {
                            "history": {
                                "status": self.STATUS_RELEASED,
                                "timestamp": datetime.utcnow(),
                                "note": f"Funds released to seller: {seller_phone}"
                            }
                        }
                    }
                )

                # Mark product as sold
                self.products_collection.update_one(
                    {"_id": ObjectId(escrow.get("product_id"))},
                    {"$set": {
                        "status": "sold",
                        "sold": True,
                        "sold_at": datetime.utcnow(),
                        "sold_to": escrow.get("buyer_phone")
                    }}
                )

                return {
                    "success": True,
                    "data": {
                        "escrow_id": escrow_id,
                        "amount": amount,
                        "seller_phone": seller_phone,
                        "transaction_id": payout_result.get("data", {}).get("transactionId"),
                        "message": "Funds successfully released to seller"
                    }
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to send money to seller",
                    "details": payout_result
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def raise_dispute(self, escrow_id, buyer_phone, reason):
        """
        Buyer raises a dispute about the transaction.

        Args:
            escrow_id: ID of the escrow payment
            buyer_phone: Buyer's phone number
            reason: Reason for the dispute

        Returns:
            dict with success status
        """
        try:
            escrow = self.escrow_collection.find_one({"_id": ObjectId(escrow_id)})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            # Verify buyer
            formatted_buyer_phone = format_phone_number(buyer_phone)
            if escrow.get("buyer_phone") != formatted_buyer_phone:
                return {"success": False, "error": "Unauthorized"}

            # Check if dispute can be raised
            if escrow.get("status") not in [self.STATUS_PAID]:
                return {"success": False, "error": f"Cannot raise dispute: Escrow status is '{escrow.get('status')}'"}

            # Update to disputed
            self.escrow_collection.update_one(
                {"_id": ObjectId(escrow_id)},
                {
                    "$set": {
                        "status": self.STATUS_DISPUTED,
                        "disputed_at": datetime.utcnow(),
                        "dispute_reason": reason
                    },
                    "$push": {
                        "history": {
                            "status": self.STATUS_DISPUTED,
                            "timestamp": datetime.utcnow(),
                            "note": f"Dispute raised: {reason}"
                        }
                    }
                }
            )

            return {
                "success": True,
                "data": {
                    "escrow_id": escrow_id,
                    "status": self.STATUS_DISPUTED,
                    "message": "Dispute has been registered. Our team will review and contact both parties."
                }
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def process_refund(self, escrow_id, admin_note=None):
        """
        Process refund to buyer (admin action after dispute resolution).

        Args:
            escrow_id: ID of the escrow payment
            admin_note: Optional admin note

        Returns:
            dict with success status
        """
        try:
            escrow = self.escrow_collection.find_one({"_id": ObjectId(escrow_id)})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            if escrow.get("status") not in [self.STATUS_PAID, self.STATUS_DISPUTED]:
                return {"success": False, "error": f"Cannot refund: Escrow status is '{escrow.get('status')}'"}

            # Send refund to buyer
            buyer_phone = escrow.get("buyer_phone")
            amount = escrow.get("amount")

            refund_result = send_money_via_at(
                buyer_phone,
                amount,
                f"Refund: {escrow.get('description', 'Purchase refund')[:50]}"
            )

            if refund_result and refund_result.get("status") == "success":
                # Update escrow
                self.escrow_collection.update_one(
                    {"_id": ObjectId(escrow_id)},
                    {
                        "$set": {
                            "status": self.STATUS_REFUNDED,
                            "refunded_at": datetime.utcnow(),
                            "refund_reference": refund_result.get("data", {}).get("transactionId"),
                            "admin_note": admin_note
                        },
                        "$push": {
                            "history": {
                                "status": self.STATUS_REFUNDED,
                                "timestamp": datetime.utcnow(),
                                "note": f"Refund processed to buyer. {admin_note or ''}"
                            }
                        }
                    }
                )

                # Unreserve product
                self.products_collection.update_one(
                    {"_id": ObjectId(escrow.get("product_id"))},
                    {"$set": {"status": "active", "reserved_by": None, "reserved_at": None}}
                )

                return {
                    "success": True,
                    "data": {
                        "escrow_id": escrow_id,
                        "amount": amount,
                        "buyer_phone": buyer_phone,
                        "transaction_id": refund_result.get("data", {}).get("transactionId"),
                        "message": "Refund processed successfully"
                    }
                }
            else:
                return {"success": False, "error": "Refund failed", "details": refund_result}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_escrow_status(self, escrow_id, requester_phone=None):
        """
        Get the current status of an escrow payment.

        Args:
            escrow_id: ID of the escrow payment
            requester_phone: Optional phone for verification

        Returns:
            dict with escrow details
        """
        try:
            escrow = self.escrow_collection.find_one({"_id": ObjectId(escrow_id)})
            if not escrow:
                return {"success": False, "error": "Escrow payment not found"}

            # If requester phone provided, verify they are buyer or seller
            if requester_phone:
                formatted_phone = format_phone_number(requester_phone)
                if formatted_phone not in [escrow.get("buyer_phone"), format_phone_number(escrow.get("seller_number", ""))]:
                    return {"success": False, "error": "Unauthorized"}

            return {
                "success": True,
                "data": {
                    "escrow_id": str(escrow["_id"]),
                    "status": escrow.get("status"),
                    "amount": escrow.get("amount"),
                    "currency": "KES",
                    "product_description": escrow.get("product_description"),
                    "buyer_phone": escrow.get("buyer_phone"),
                    "seller_phone": escrow.get("seller_phone"),
                    "created_at": escrow.get("created_at").isoformat() if escrow.get("created_at") else None,
                    "paid_at": escrow.get("paid_at").isoformat() if escrow.get("paid_at") else None,
                    "confirmed_at": escrow.get("confirmed_at").isoformat() if escrow.get("confirmed_at") else None,
                    "released_at": escrow.get("released_at").isoformat() if escrow.get("released_at") else None,
                    "confirmation_deadline": escrow.get("confirmation_deadline").isoformat() if escrow.get("confirmation_deadline") else None,
                    "history": escrow.get("history", [])
                }
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_buyer_escrows(self, buyer_phone):
        """Get all escrow payments for a buyer"""
        try:
            formatted_phone = format_phone_number(buyer_phone)
            escrows = self.escrow_collection.find({"buyer_phone": formatted_phone}).sort("created_at", -1)

            result = []
            for escrow in escrows:
                result.append({
                    "escrow_id": str(escrow["_id"]),
                    "status": escrow.get("status"),
                    "amount": escrow.get("amount"),
                    "product_description": escrow.get("product_description"),
                    "created_at": escrow.get("created_at").isoformat() if escrow.get("created_at") else None
                })

            return {"success": True, "data": result}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_seller_escrows(self, seller_phone):
        """Get all escrow payments for a seller"""
        try:
            formatted_phone = format_phone_number(seller_phone)
            escrows = self.escrow_collection.find({
                "$or": [
                    {"seller_phone": formatted_phone},
                    {"seller_number": {"$regex": seller_phone.replace("+", "")}}
                ]
            }).sort("created_at", -1)

            result = []
            for escrow in escrows:
                result.append({
                    "escrow_id": str(escrow["_id"]),
                    "status": escrow.get("status"),
                    "amount": escrow.get("amount"),
                    "product_description": escrow.get("product_description"),
                    "buyer_phone": escrow.get("buyer_phone"),
                    "created_at": escrow.get("created_at").isoformat() if escrow.get("created_at") else None
                })

            return {"success": True, "data": result}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def process_auto_releases(self):
        """
        Process automatic releases for escrows past confirmation deadline.
        Should be run periodically via cron/scheduler.
        """
        try:
            # Find escrows past deadline
            expired_escrows = self.escrow_collection.find({
                "status": self.STATUS_PAID,
                "confirmation_deadline": {"$lt": datetime.utcnow()}
            })

            results = []
            for escrow in expired_escrows:
                escrow_id = str(escrow["_id"])
                # Add history entry
                self.escrow_collection.update_one(
                    {"_id": escrow["_id"]},
                    {"$push": {
                        "history": {
                            "status": "auto_release",
                            "timestamp": datetime.utcnow(),
                            "note": "Auto-released after confirmation deadline"
                        }
                    }}
                )
                # Release funds
                release_result = self.release_funds(escrow_id)
                results.append({
                    "escrow_id": escrow_id,
                    "result": release_result
                })

            return {"success": True, "processed": len(results), "results": results}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def process_expired_payments(self):
        """
        Cancel escrows with expired payment windows.
        Should be run periodically via cron/scheduler.
        """
        try:
            expired = self.escrow_collection.find({
                "status": self.STATUS_PENDING,
                "payment_expiry": {"$lt": datetime.utcnow()}
            })

            count = 0
            for escrow in expired:
                self._expire_escrow(escrow["_id"])
                count += 1

            return {"success": True, "expired_count": count}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _expire_escrow(self, escrow_id):
        """Internal method to expire an escrow"""
        escrow = self.escrow_collection.find_one({"_id": escrow_id})
        if escrow:
            self.escrow_collection.update_one(
                {"_id": escrow_id},
                {
                    "$set": {"status": self.STATUS_EXPIRED, "expired_at": datetime.utcnow()},
                    "$push": {
                        "history": {
                            "status": self.STATUS_EXPIRED,
                            "timestamp": datetime.utcnow(),
                            "note": "Payment window expired"
                        }
                    }
                }
            )
            # Unreserve product
            if escrow.get("product_id"):
                self.products_collection.update_one(
                    {"_id": ObjectId(escrow["product_id"])},
                    {"$set": {"status": "active", "reserved_by": None, "reserved_at": None}}
                )

    def _cancel_escrow(self, escrow_id, reason):
        """Internal method to cancel an escrow"""
        escrow = self.escrow_collection.find_one({"_id": escrow_id})
        if escrow:
            self.escrow_collection.update_one(
                {"_id": escrow_id},
                {
                    "$set": {"status": self.STATUS_CANCELLED, "cancelled_at": datetime.utcnow()},
                    "$push": {
                        "history": {
                            "status": self.STATUS_CANCELLED,
                            "timestamp": datetime.utcnow(),
                            "note": reason
                        }
                    }
                }
            )
            # Unreserve product
            if escrow.get("product_id"):
                self.products_collection.update_one(
                    {"_id": ObjectId(escrow["product_id"])},
                    {"$set": {"status": "active", "reserved_by": None, "reserved_at": None}}
                )
