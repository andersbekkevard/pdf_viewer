"""Build reportlab_base14.pdf: running text in the non-embedded base-14 fonts.

A viewer must substitute a local font for Times-Roman, Helvetica and Courier.
On macOS that substitute is a complete system font (Times carries polytonic
Greek), so its bounding box is far taller than any glyph this text uses.

    uv run --with reportlab python reportlab_base14.py
"""
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

TEXT = (
    "It is practically more useful. Parameters of engineering importance such as "
    "time, bandwidth, number of relays, etc., tend to vary linearly with the "
    "logarithm of the number of possibilities. For example, adding one relay to a "
    "group doubles the number of possible states of the relays. It adds 1 to the "
    "base 2 logarithm of this number. Doubling the time roughly squares the number "
    "of possible messages, or doubles the logarithm, etc."
)


def paragraph(c, font, y, size=10, leading=12, width=468):
    c.setFont(font, size)
    line = ""
    for word in TEXT.split():
        trial = (line + " " + word).strip()
        if c.stringWidth(trial, font, size) > width:
            c.drawString(72, y, line)
            y -= leading
            line = word
        else:
            line = trial
    c.drawString(72, y, line)
    return y - 2 * leading


c = canvas.Canvas("reportlab_base14.pdf", pagesize=letter, invariant=1)
y = 720
for font in ("Times-Roman", "Times-Italic", "Helvetica", "Courier"):
    y = paragraph(c, font, y)
c.save()
