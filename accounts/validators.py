from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class LetterAndDigitPasswordValidator:
    """Require at least one letter and one digit, as specified by the SRS."""

    def validate(self, password, user=None):
        if not any(character.isalpha() for character in password) or not any(
            character.isdigit() for character in password
        ):
            raise ValidationError(
                _("Password must contain at least one letter and one digit."),
                code="letter_and_digit",
            )

    def get_help_text(self):
        return _("Your password must contain at least one letter and one digit.")
