"""Generate the fictional sample PDFs in ./sample_docs (all names and figures are made up)."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent / "sample_docs"
OUT.mkdir(exist_ok=True)

base = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=19, alignment=TA_CENTER,
                       textColor=colors.HexColor("#1b2438"), spaceAfter=4)
SUB = ParagraphStyle("s", parent=base["Normal"], fontSize=11, alignment=TA_CENTER,
                     textColor=colors.HexColor("#5b6678"), spaceAfter=18)
H = ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, spaceBefore=14,
                   spaceAfter=6, textColor=colors.HexColor("#1f3a8a"))
B = ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica", fontSize=10.5, leading=15.5, spaceAfter=7)


def build(filename, footer, pages):
    total = len(pages)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#2f5bea"))
        canvas.rect(0, letter[1] - 10, letter[0], 10, stroke=0, fill=1)
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#7a8599"))
        canvas.drawString(inch, 0.6 * inch, footer)
        canvas.drawRightString(letter[0] - inch, 0.6 * inch, f"Page {canvas.getPageNumber()} of {total}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(OUT / filename), pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=inch, bottomMargin=inch, title=footer, author="Fictional sample data")
    story = []
    for i, items in enumerate(pages):
        for kind, text in items:
            if kind == "title":
                story.append(Paragraph(text, TITLE))
            elif kind == "sub":
                story.append(Paragraph(text, SUB))
            elif kind == "h":
                story.append(Paragraph(text, H))
            else:
                story.append(Paragraph(text, B))
        if i < total - 1:
            story.append(PageBreak())
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)


def p(text):
    return ("p", text)


# ------------------------------------------------------------------ Unit 302 lease (4 pages)
build("Unit_302_Lease_Agreement.pdf", "Unit 302 — Residential Lease Agreement", [
    [("title", "RESIDENTIAL LEASE AGREEMENT"), ("sub", "Maple Ridge Residences — Unit 302"),
     p('This Residential Lease Agreement (the "Lease") is made on March 12, 2026, between Maple Ridge Property '
       'Management LLC ("Landlord") and the Tenant identified below. The Landlord agrees to lease the Premises to '
       'the Tenant, and the Tenant agrees to lease the Premises from the Landlord, on the terms set out in this Lease.'),
     ("h", "1. Parties and Premises"),
     p("<b>Tenant:</b> Marcus Ellison"),
     p("<b>Property:</b> Maple Ridge Residences"),
     p("<b>Unit:</b> 302"),
     p("<b>Address:</b> 1450 Maple Ridge Drive, Unit 302, Riverton"),
     p("1.2 Occupancy. The Premises will be occupied only by the Tenant and one additional approved adult occupant. "
       "Any other occupant requires the Landlord's prior written consent."),
     p("1.3 Use of Premises. The Premises may be used as a private residence only. No business activity involving "
       "customer visits is permitted.")],
    [("h", "2. Rent and Security Deposit"),
     p("2.1 Monthly Rent. The Tenant shall pay monthly rent of $1,850.00, due on or before the first day of each "
       "calendar month."),
     p("2.2 Late Charges. If rent is not received by the fifth day of the month, the Tenant shall pay a late fee of "
       "$75.00."),
     p("2.3 Security Deposit. The Tenant has paid a security deposit of $1,850.00. The Landlord will return the "
       "deposit, less any lawful deductions for unpaid rent or damage beyond normal wear and tear, within 30 days "
       "after the Tenant moves out."),
     p("2.4 Method of Payment. Rent may be paid through the online resident portal or by check made payable to "
       "Maple Ridge Property Management LLC."),
     p("2.5 Returned Payments. A fee of $35.00 applies to any payment that is returned by the bank.")],
    [("h", "3. Term of Lease"),
     p("3.1 Lease Start Date: April 1, 2026."),
     p("3.2 Lease End Date: March 31, 2027. This Lease expires on that date unless it is renewed in writing by "
       "both parties."),
     p("3.3 Renewal. The Landlord will send a renewal offer at least 90 days before the Lease End Date. The Tenant "
       "must respond in writing at least 60 days before the Lease End Date."),
     ("h", "4. Maintenance and Repairs"),
     p("4.1 Landlord Responsibilities. The Landlord is responsible for the structure of the building, plumbing, "
       "heating and cooling systems, electrical wiring, and any appliances provided by the Landlord."),
     p("4.2 Tenant Responsibilities. The Tenant is responsible for keeping the Premises clean, replacing light "
       "bulbs and smoke detector batteries, disposing of garbage properly, and reporting damage promptly. The "
       "Tenant pays for repairs needed because of misuse or negligence."),
     p("4.3 Maintenance Requests. Requests must be submitted through the resident portal. Non-emergency requests "
       "are handled within three business days and emergencies within 24 hours.")],
    [("h", "5. Utilities and Other Terms"),
     p("5.1 Utilities. The Tenant pays for electricity and internet service. The Landlord pays for water, sewer "
       "and trash collection."),
     p("5.2 Pets. No pets are allowed without the Landlord's written consent. An approved pet requires a one-time "
       "pet deposit of $300.00."),
     p("5.3 Smoking. Smoking and vaping are not permitted inside the Premises or in common areas."),
     p("5.4 Parking. The Tenant has one assigned parking space, number 14."),
     p("5.5 Entry by Landlord. The Landlord may enter the Premises with at least 24 hours' notice, except in an "
       "emergency."),
     ("h", "6. Signatures"),
     p("Tenant signature: Marcus Ellison (signed March 12, 2026)"),
     p("Landlord signature: Maple Ridge Property Management LLC (signed March 12, 2026)")],
])

# ------------------------------------------------------------------ Unit 105 rental agreement (3 pages)
build("Unit_105_Rental_Agreement.pdf", "Unit 105 — Residential Rental Agreement", [
    [("title", "RESIDENTIAL RENTAL AGREEMENT"), ("sub", "Harbor View Apartments — Unit 105"),
     p('This Residential Rental Agreement (the "Agreement") is entered into on December 15, 2025, by and between '
       'Harbor View Apartments LLC ("Landlord") and Sofia Marchetti ("Resident") for the rental of the apartment '
       'described below.'),
     ("h", "A. The Apartment"),
     p("<b>Property:</b> Harbor View Apartments"),
     p("<b>Unit:</b> 105"),
     p("<b>Address:</b> 220 Harbor Street, Westport"),
     p("Term. The term of this Agreement is January 1, 2026 through December 31, 2026. After that date the tenancy "
       "continues month to month unless either party gives 30 days' written notice."),
     p("Occupancy. Only the Resident may live in the apartment unless the Landlord approves additional occupants "
       "in writing.")],
    [("h", "B. Rent and Deposit"),
     p("Monthly Rent: The Resident shall pay $1,425.00 per month, due on the first day of each month."),
     p("Late Fee: Rent received after the sixth day of the month incurs a late fee of $60.00."),
     p("Security Deposit: The Resident has paid a security deposit of $1,425.00, held in a separate account and "
       "returned within 21 days after move-out, less lawful deductions."),
     p("Utilities: The Resident pays for electricity and gas. Water, sewer and trash collection are included in "
       "the rent."),
     p("Payment Methods: Payments are accepted through the online portal, by bank transfer, or by check.")],
    [("h", "C. Maintenance and Rules"),
     p("Landlord Repairs: The Landlord repairs plumbing, locks, heating, and all appliances provided with the "
       "apartment. Urgent problems can be reported to the 24-hour maintenance line."),
     p("Resident Care: The Resident keeps drains free of blockages, replaces smoke detector batteries, and reports "
       "leaks or pests immediately. The Resident pays for damage caused by misuse."),
     p("Quiet Hours: Quiet hours are from 10:00 p.m. to 7:00 a.m."),
     p("Pets: One cat or small dog under 25 pounds is allowed with a one-time pet fee of $250.00."),
     p("Parking: Parking is available in the shared lot on a first-come basis."),
     ("h", "D. Signatures"),
     p("Resident signature: Sofia Marchetti (signed December 15, 2025)"),
     p("Landlord signature: Harbor View Apartments LLC (signed December 15, 2025)")],
])

# ------------------------------------------------------------------ Maintenance service agreement (3 pages)
build("Maple_Ridge_Maintenance_Service_Agreement.pdf", "Maple Ridge Residences — Maintenance Service Agreement", [
    [("title", "MAINTENANCE SERVICE AGREEMENT"), ("sub", "Maple Ridge Residences"),
     p('This Maintenance Service Agreement (the "Agreement") is made on April 20, 2026, between Maple Ridge '
       'Property Management LLC ("Owner") and Brightline Facilities Services ("Contractor").'),
     ("h", "1. Parties and Property"),
     p("<b>Property:</b> Maple Ridge Residences"),
     p("<b>Contractor:</b> Brightline Facilities Services"),
     p("<b>Owner:</b> Maple Ridge Property Management LLC"),
     p("1.2 Service Period. The service period is May 1, 2026 through April 30, 2027."),
     p("1.3 Renewal. The Agreement renews for another 12 months unless either party gives 30 days' written "
       "notice.")],
    [("h", "2. Scope of Services and Response Times"),
     p("2.1 Scope. The Contractor provides routine plumbing, electrical, heating and cooling, and appliance "
       "repairs, as well as upkeep of hallways, stairwells and other common areas."),
     p("2.2 Emergency Requests. Emergency requests, including water leaks, loss of heat and electrical hazards, "
       "must receive a technician on site within 2 hours."),
     p("2.3 Routine Requests. Routine requests must be completed within three business days of being assigned."),
     p("2.4 Monthly Service Fee. The Owner pays the Contractor a monthly service fee of $4,200.00, invoiced on the "
       "last day of each month and payable within 15 days.")],
    [("h", "3. Responsibilities and Terms"),
     p("3.1 Contractor Responsibilities. The Contractor provides licensed technicians, carries general liability "
       "insurance of $1,000,000, and submits a monthly work order summary to the Owner."),
     p("3.2 Owner Responsibilities. The Owner provides access to the buildings, a current list of residents, and "
       "approval for any single repair where parts cost more than $250.00."),
     p("3.3 Termination. Either party may end this Agreement with 30 days' written notice."),
     ("h", "4. Signatures"),
     p("Owner signature: Maple Ridge Property Management LLC (signed April 20, 2026)"),
     p("Contractor signature: Brightline Facilities Services (signed April 20, 2026)")],
])

print("Sample PDFs written to", OUT)
