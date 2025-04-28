from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed, MultipleFileField
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, BooleanField, SelectField
from wtforms.validators import DataRequired, Optional

class SigningForm(FlaskForm):
    ipa_file = FileField('IPA File', validators=[
        FileRequired(),
        FileAllowed(['ipa'], 'IPA files only!')
    ])
    
    p12_file = FileField('P12 Certificate', validators=[
        FileRequired(),
        FileAllowed(['p12'], 'P12 certificate files only!')
    ])
    
    provision_file = FileField('Mobile Provision Profile', validators=[
        FileRequired(),
        FileAllowed(['mobileprovision'], 'Mobile provision files only!')
    ])
    
    p12_password = PasswordField('P12 Password', validators=[DataRequired()])
    
    # Optional fields for basic customization
    bundle_id = StringField('Bundle ID (Optional)', validators=[Optional()])
    bundle_name = StringField('Bundle Name (Optional)', validators=[Optional()])
    bundle_version = StringField('Bundle Version (Optional)', validators=[Optional()])
    
    # App icon customization
    app_icon = FileField('Custom App Icon (Optional)', validators=[
        FileAllowed(['png', 'jpg', 'jpeg'], 'Image files only!')
    ])
    
    submit = SubmitField('Sign App')

class AdvancedSigningForm(FlaskForm):
    ipa_file = FileField('IPA File', validators=[
        FileRequired(),
        FileAllowed(['ipa'], 'IPA files only!')
    ])
    
    p12_file = FileField('P12 Certificate', validators=[
        FileRequired(),
        FileAllowed(['p12'], 'P12 certificate files only!')
    ])
    
    provision_file = FileField('Mobile Provision Profile', validators=[
        FileRequired(),
        FileAllowed(['mobileprovision'], 'Mobile provision files only!')
    ])
    
    p12_password = PasswordField('P12 Password', validators=[DataRequired()])
    
    # App customization
    bundle_id = StringField('Bundle ID', validators=[Optional()])
    bundle_name = StringField('Bundle Name', validators=[Optional()])
    bundle_version = StringField('Bundle Version', validators=[Optional()])
    
    # App icon customization
    app_icon = FileField('Custom App Icon (PNG)', validators=[
        FileAllowed(['png', 'jpg', 'jpeg'], 'Image files only!')
    ])
    
    # Advanced options
    entitlements = TextAreaField('Custom Entitlements (XML/Plist format)', validators=[Optional()])
    
    dylib_files = MultipleFileField('Dylib Files for Injection (Optional)', validators=[
        FileAllowed(['dylib'], 'Dylib files only!')
    ])
    
    compression_level = SelectField('Compression Level', 
        choices=[('0', 'No Compression (0)'), 
                 ('1', 'Fastest (1)'), 
                 ('6', 'Default (6)'), 
                 ('9', 'Best Compression (9)')],
        default='9',
        validators=[Optional()]
    )
    
    weak_signature = BooleanField('Weak Signature (for older iOS versions)', default=False)
    force_signature = BooleanField('Force Signature (ignore errors)', default=False)
    verbose = BooleanField('Verbose Output', default=False)
    
    submit = SubmitField('Sign App (Advanced)')