"""
Django settings for solotodo_core project.

Generated by 'django-admin startproject' using Django 1.11.3.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""
import logging
import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
from decimal import Decimal
from django_filters import STRICTNESS
from elasticsearch import Elasticsearch


def _(s):
    return s

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django_extensions',
    'mathfilters',
    'guardian',
    'rest_framework',
    'rest_framework.authtoken',
    'allauth',
    'allauth.account',
    'rest_auth',
    'rest_auth.registration',
    'django_filters',
    'crispy_forms',
    'storages',
    'sorl.thumbnail',
    'custom_user',
    'corsheaders',
    'django_premailer',
    'gtin_fields',
    'rest_framework_tracking',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.facebook',
    'metamodel',
    'solotodo',
    'hardware',
    'category_templates',
    'reports',
    'mailing',
    'category_specs_forms',
    'category_columns',
    'entity_subscriptions',
    'wtb',
    'navigation',
    'carousel_slides',
]

SITE_ID = 1

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'querycount.middleware.QueryCountMiddleware',
]

ROOT_URLCONF = 'solotodo_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'solotodo_core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.11/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'solotodo_core',
    }
}


# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.'
                'UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.'
                'MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.'
                'CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.'
                'NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'es'

LANGUAGES = [
    ('en', _('English')),
    ('es', _('Spanish')),
]

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/

STATIC_URL = '/static/'


#############################################################################
# Customized settings
#############################################################################

AUTH_USER_MODEL = 'solotodo.SoloTodoUser'

DEFAULT_FILE_STORAGE = 'solotodo_core.s3utils.MediaRootS3Boto3Storage'

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
    'guardian.backends.ObjectPermissionBackend',
)

GEOIP_PATH = BASE_DIR

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'LOCATION': '127.0.0.1:11211',
    }
}

#############################################################################
# Celery configurations
#############################################################################

CELERY_ENABLE_UTC = True

CELERY_BROKER_URL = \
    'amqp://solotodo_core:solotodo_core@localhost/solotodo_core'
CELERY_RESULT_BACKEND = 'rpc://'

CELERY_IMPORTS = (
    'storescraper.store'
)

CELERYD_TASK_TIME_LIMIT = 300

##############################################################################
# Django storages configuration
##############################################################################

AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
AWS_STORAGE_BUCKET_NAME = 'solotodo-core'
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_REGION_NAME = 'us-east-1'

##############################################################################
# DRF Configuration
##############################################################################

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    )
}

##############################################################################
# CORS headers configuration
##############################################################################

CORS_ORIGIN_WHITELIST = ['localhost:3000', ]

###############################################################################
# Django-guardian Configuration
###############################################################################

ANONYMOUS_USER_NAME = 'anonymous@solotodo.com'

###############################################################################
# Django QueryCount configuration
###############################################################################

QUERYCOUNT = {
    'THRESHOLDS': {
        'MEDIUM': 50,
        'HIGH': 200,
        'MIN_TIME_TO_LOG': 0,
        'MIN_QUERY_COUNT_TO_LOG': 0
    },
    'IGNORE_REQUEST_PATTERNS': [],
    'IGNORE_SQL_PATTERNS': [],
    'DISPLAY_DUPLICATES': None
}

###############################################################################
# Django crispy forms configuration
###############################################################################

CRISPY_TEMPLATE_PACK = 'bootstrap3'

###############################################################################
# Django filter configuration
###############################################################################

FILTERS_STRICTNESS = STRICTNESS.RAISE_VALIDATION_ERROR

##############################################################################
# Premailer configuration
##############################################################################

PREMAILER_OPTIONS = {
    'strip_important': False,
    'cssutils_logging_level': logging.ERROR
}

##############################################################################
# Django-codemirror
##############################################################################

CODEMIRROR_PATH = 'node_modules/codemirror'

##############################################################################
# PubNub configuration
##############################################################################

BACKEND_CHANNEL = 'backend'
PUBNUB = None

##############################################################################
# all-auth settings
##############################################################################

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_ADAPTER = 'solotodo.solotodo_account_adapter.SoloTodoAccountAdapter'
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'

##############################################################################
# rest-auth configuration
##############################################################################

OLD_PASSWORD_FIELD_ENABLED = True

##############################################################################
# SORL Thumbnail settings
##############################################################################

THUMBNAIL_FORMAT = 'PNG'

##############################################################################
# Made up settings
##############################################################################

DEFAULT_CURRENCY = 4
DEFAULT_COUNTRY = 1
BOT_USERNAME = 'solobot@solotodo.com'
BACKEND_HOST = 'http://localhost:3000/'
CELL_CATEGORY = 6
CELL_PLAN_CATEGORY = 20

METAMODEL = {
    'DEBUG': False,
    'ADDITIONAL_ELASTICSEARCH_FIELDS_FUNCTIONS': [
        'solotodo.metamodel_custom_functions.brand_unicode.brand_unicode',
        'solotodo.metamodel_custom_functions.notebooks.additional_es_fields',
        'solotodo.metamodel_custom_functions.hardware.additional_es_fields',
        'solotodo.metamodel_custom_functions.electro.additional_es_fields',
        'solotodo.metamodel_custom_functions.smartphones.additional_es_fields'
    ],
    'MEDIA_PATH': 'products',
    'UNICODE_FUNCTIONS': [
        'solotodo.metamodel_custom_functions.hardware.unicode_function',
        'solotodo.metamodel_custom_functions.electro.unicode_function',
        'solotodo.metamodel_custom_functions.smartphones.unicode_function',
    ],
    'ORDERING_FUNCTIONS': [
        'solotodo.metamodel_custom_functions.notebooks.ordering_value'
    ]
}

ES = Elasticsearch([{"host": "localhost", "port": 9201}])
ES_PRODUCTS_INDEX = 'products'

CURRENCYLAYER_API_ACCESS_KEY = ''

REPORTS_PURPOSE_ID = 3

ENTITY_ASSOCIATION_AMOUNT = Decimal(0)
WTB_ENTITY_ASSOCIATION_AMOUNT = Decimal(0)

SOLOTODO_COM_SITE_ID = 1

LINIO_AFFILIATE_SETTINGS = {
    'STORE_ID': None,
    'AFFILIATE_ID': None
}
