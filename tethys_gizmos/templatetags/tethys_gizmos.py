"""
********************************************************************************
* Name: tethys_gizmos.py
* Author: Nathan Swain
* Created On: 2014
* Copyright: (c) Brigham Young University 2014
* License: BSD 2-Clause
********************************************************************************
"""

import json
import time
import inspect
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django import template
from django.template.loader import get_template
from django.template import TemplateSyntaxError
from django.templatetags.static import static
from django.core.serializers.json import DjangoJSONEncoder

from tethys_apps.harvester import SingletonHarvester

from ..gizmo_options.base import TethysGizmoOptions
import tethys_sdk.gizmos
from tethys_portal.optional_dependencies import optional_import

# optional imports
plotly = optional_import("plotly")
get_plotlyjs = optional_import("get_plotlyjs", from_module="plotly.offline.offline")

GIZMO_NAME_PROPERTY = "gizmo_name"
GIZMO_NAME_MAP = {}
EXTENSION_PATH_MAP = {}

# Add gizmos to GIZMO_NAME_MAP
for _, cls in tethys_sdk.gizmos.__dict__.items():
    if (
        inspect.isclass(cls)
        and issubclass(cls, TethysGizmoOptions)
        and hasattr(cls, GIZMO_NAME_PROPERTY)
    ):
        GIZMO_NAME_MAP[cls.gizmo_name] = cls


# Add extension gizmos to the GIZMO_NAME_MAP
harvester = SingletonHarvester()
extension_modules = harvester.extension_modules

for _, extension_module in extension_modules.items():
    try:
        gizmo_module = __import__("{}.gizmos".format(extension_module), fromlist=[""])
        for _, cls in gizmo_module.__dict__.items():
            if (
                inspect.isclass(cls)
                and issubclass(cls, TethysGizmoOptions)
                and hasattr(cls, GIZMO_NAME_PROPERTY)
            ):
                GIZMO_NAME_MAP[cls.gizmo_name] = cls
                gizmo_module_path = gizmo_module.__path__[0]
                EXTENSION_PATH_MAP[cls.gizmo_name] = str(
                    Path(gizmo_module_path).parent.absolute()
                )
    except ImportError:
        # TODO: Add Log?
        continue

register = template.Library()

MODALS_OUTPUT_TYPE = "modals"
CSS_OUTPUT_TYPE = "css"
CSS_GLOBAL_OUTPUT_TYPE = "global_css"
JS_OUTPUT_TYPE = "js"
JS_GLOBAL_OUTPUT_TYPE = "global_js"
CSS_EXTENSION = "css"
JS_EXTENSION = "js"
EXTERNAL_INDICATOR = "://"
CSS_OUTPUT_TYPES = (CSS_OUTPUT_TYPE, CSS_GLOBAL_OUTPUT_TYPE)
JS_OUTPUT_TYPES = (JS_OUTPUT_TYPE, JS_GLOBAL_OUTPUT_TYPE)
GLOBAL_OUTPUT_TYPES = (CSS_GLOBAL_OUTPUT_TYPE, JS_GLOBAL_OUTPUT_TYPE)
VALID_OUTPUT_TYPES = (MODALS_OUTPUT_TYPE, *CSS_OUTPUT_TYPES, *JS_OUTPUT_TYPES)


class HighchartsDateEncoder(DjangoJSONEncoder):
    """
    Special Json Encoder for Tethys
    """

    def default(self, obj):
        # Highcharts date serializer
        if isinstance(obj, datetime):
            return time.mktime(obj.timetuple()) * 1000
        return super().default(obj)


class SetVarNode(template.Node):
    def __init__(self, var_name, var_value):
        self.var_names = var_name.split(".")
        self.var_name = self.var_names.pop()
        self.var_value = var_value

    def render(self, context):
        try:
            value = template.Variable(self.var_value).resolve(context)
        except template.VariableDoesNotExist:
            value = ""

        for name in self.var_names:
            context = context[name]

        context[self.var_name] = value

        return ""


@register.tag(name="set")
def set_var(parser, token):
    """
    {% set some_var = '123' %}
    """
    parts = token.split_contents()
    if len(parts) < 4:
        raise template.TemplateSyntaxError(
            "'set' tag must be of the form: {% set <var_name> = <var_value> %}"
        )

    return SetVarNode(parts[1], parts[3])


@register.filter(is_safe=True)
def isstring(value):
    """
    Filter that returns a type
    """
    if value is str:
        return True
    else:
        return False


@register.filter
def return_item(container, i):
    try:
        return container[i]
    except Exception:
        return None


def json_date_handler(obj):
    if isinstance(obj, datetime):
        return time.mktime(obj.timetuple()) * 1000
    else:
        return obj


@register.filter
def jsonify(data):
    """
    Convert python data structures into a JSON string
    """
    return json.dumps(data, default=json_date_handler)


@register.filter
def codify(data):
    return data.lower().replace(" ", "-")


@register.filter
def divide(value, divisor):
    """
    Divide value by divisor
    """
    v = float(value)
    d = float(divisor)

    return v / d


class TethysGizmoIncludeDependency(template.Node):
    """
    Custom template include node that returns Tethys gizmos
    """

    def __init__(self, gizmo_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._load_gizmo_name(gizmo_name)

    def _load_gizmo_name(self, gizmo_name):
        """
        This loads the rendered gizmos into context
        """
        self.gizmo_name = gizmo_name

        if self.gizmo_name is not None:
            # Handle case where gizmo_name is a string literal
            if self.gizmo_name[0] in ('"', "'"):
                self.gizmo_name = self.gizmo_name.replace("'", "")
                self.gizmo_name = self.gizmo_name.replace('"', "")

    def _load_gizmos_rendered(self, context):
        """
        This loads the rendered gizmos into context
        """
        # Add gizmo name to 'gizmos_rendered' context variable (used to load static  libraries
        if "gizmos_rendered" not in context:
            context.update({"gizmos_rendered": []})

        # add the gizmo in the tag to gizmos_rendered list
        if self.gizmo_name is not None:
            if self.gizmo_name not in context["gizmos_rendered"]:
                if self.gizmo_name not in GIZMO_NAME_MAP:
                    raise TemplateSyntaxError(
                        'The gizmo name "{0}" is invalid.'.format(self.gizmo_name)
                    )
                context["gizmos_rendered"].append(self.gizmo_name)

    def render(self, context):
        """
        Load in the gizmos to be rendered
        """
        try:
            self._load_gizmos_rendered(context)
        except Exception as e:
            if settings.TEMPLATE_DEBUG:
                raise e

        return ""


class TethysGizmoIncludeNode(TethysGizmoIncludeDependency):
    """
    Custom template include node that returns Tethys gizmos
    """

    def __init__(self, options, gizmo_name, *args, **kwargs):
        self.options = options
        super().__init__(gizmo_name, *args, **kwargs)

    def render(self, context):
        resolved_options = template.Variable(self.options).resolve(context)

        try:
            if self.gizmo_name is None or self.gizmo_name not in GIZMO_NAME_MAP:
                if hasattr(resolved_options, GIZMO_NAME_PROPERTY):
                    self._load_gizmo_name(resolved_options.gizmo_name)
                else:
                    raise TemplateSyntaxError(
                        "A valid gizmo name is required for this input format."
                    )

            self._load_gizmos_rendered(context)

            # Derive path to gizmo template
            if self.gizmo_name not in EXTENSION_PATH_MAP:
                # Determine path to gizmo template
                gizmo_templates_root = str(Path("tethys_gizmos/gizmos"))

            else:
                gizmo_templates_root = str(
                    Path(EXTENSION_PATH_MAP[self.gizmo_name]) / "templates" / "gizmos"
                )

            gizmo_file_name = "{0}.html".format(self.gizmo_name)
            template_name = str(Path(gizmo_templates_root) / gizmo_file_name)

            # reset gizmo_name in case Node is rendered with different options
            self._load_gizmo_name(None)

            # Retrieve the gizmo template and render
            t = get_template(template_name)
            return t.render(resolved_options)

        except Exception:
            if hasattr(settings, "TEMPLATES"):
                for template_settings in settings.TEMPLATES:
                    if (
                        "OPTIONS" in template_settings
                        and "debug" in template_settings["OPTIONS"]
                        and template_settings["OPTIONS"]["debug"]
                    ):
                        raise
            return ""


@register.tag
def gizmo(parser, token):
    """
    Similar to the include tag, gizmo loads special templates called gizmos that come with the django-tethys_gizmo
    app. Gizmos provide tools for developing user interface elements with minimal code. Examples include date pickers,
    maps, and interactive plots.

    To insert a gizmo, use the "gizmo" tag and give it a Gizmo object of configuration parameters.

    Example::

        {% load tethys %}

        {% gizmo options %}

    The old method of using the gizmo name is still supported.

    Example::

        {% load tethys %}

        {% gizmo gizmo_name options %}

    .. note: The Gizmo "options" object must be a template context variable.

    .. note: All supporting css and javascript libraries are loaded using the gizmo_dependency tag (see below).
    """
    gizmo_arg_list = token.split_contents()[1:]
    if len(gizmo_arg_list) == 1:
        gizmo_options = gizmo_arg_list[0]
        gizmo_name = None
    elif len(gizmo_arg_list) == 2:
        gizmo_name, gizmo_options = gizmo_arg_list
    else:
        raise TemplateSyntaxError(
            '"gizmo" tag takes at least one argument: the gizmo options object.'
        )

    return TethysGizmoIncludeNode(gizmo_options, gizmo_name)


@register.tag
def import_gizmo_dependency(parser, token):
    """
    The gizmo dependency tag will add the dependencies for the gizmo specified
    so that is will be loaded when using the *gizmo_dependencies* tag.

    To manually import a gizmo's dependency, use the "import_gizmo_dependency"
    tag and give it the name of a gizmo. It needs to be inside of the
    "import_gizmos" block.

    Example::

        {% load tethys %}

        {% block import_gizmos %}
            {% import_gizmo_dependency example_gizmo %}
            {% import_gizmo_dependency "example_gizmo" %}
        {% endblock %}

    .. note: All supporting css and javascript libraries are loaded using the gizmo_dependencies tag (see below).
    """
    try:
        tag_name, gizmo_name = token.split_contents()

    except ValueError:
        raise TemplateSyntaxError(
            '"%s" tag requires exactly one argument' % token.contents.split()[0]
        )

    return TethysGizmoIncludeDependency(gizmo_name)


class TethysGizmoDependenciesNode(template.Node):
    """
    Loads gizmo dependencies and renders in "script" or "link" tag appropriately.
    """

    def __init__(self, output_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_type = output_type

    @staticmethod
    def _append_dependency(dependency, dependency_list):
        """
        Add dependency to list if not already in list
        """
        if EXTERNAL_INDICATOR in dependency:
            static_url = dependency
        else:
            static_url = static(dependency)

        # Only append dependencies if they do not already exist
        if static_url not in dependency_list:
            # Lookup the static url given the path
            dependency_list.append(static_url)

    def load_gizmos(self, context):
        # initialize lists to store gizmo dependencies
        for output_type in VALID_OUTPUT_TYPES:
            list_name = f"gizmo_{output_type}_list"
            if list_name not in context.render_context:
                context.render_context[list_name] = []

        # add all gizmos in context to be loaded
        for dict_element in context:
            for key in dict_element:
                resolved_options = template.Variable(key).resolve(context)
                if hasattr(resolved_options, GIZMO_NAME_PROPERTY):
                    if resolved_options.gizmo_name not in context["gizmos_rendered"]:
                        context["gizmos_rendered"].append(resolved_options.gizmo_name)

        for rendered_gizmo in context["gizmos_rendered"]:
            # Retrieve the "gizmo_dependencies" module and find the appropriate function
            dependencies_module = GIZMO_NAME_MAP[rendered_gizmo]

            for dependency in dependencies_module.get_gizmo_css():
                self._append_dependency(
                    dependency, context.render_context["gizmo_css_list"]
                )
            for dependency in dependencies_module.get_gizmo_js():
                self._append_dependency(
                    dependency, context.render_context["gizmo_js_list"]
                )
            for dependency in dependencies_module.get_vendor_css():
                self._append_dependency(
                    dependency, context.render_context["gizmo_global_css_list"]
                )
            for dependency in dependencies_module.get_vendor_js():
                self._append_dependency(
                    dependency, context.render_context["gizmo_global_js_list"]
                )
            for modal in dependencies_module.get_gizmo_modals():
                context.render_context["gizmo_modals_list"].append(modal)

        # Add the main gizmo dependencies last
        for dependency in TethysGizmoOptions.get_tethys_gizmos_css():
            self._append_dependency(
                dependency, context.render_context["gizmo_css_list"]
            )
        for dependency in TethysGizmoOptions.get_tethys_gizmos_js():
            self._append_dependency(dependency, context.render_context["gizmo_js_list"])

        context.render_context["gizmo_dependencies_loaded"] = True

    def render(self, context):
        """
        Load in Modals/JS/CSS dependencies to HTML
        """
        # NOTE: Use render_context as it is recommended to do so here
        # https://docs.djangoproject.com/en/1.10/howto/custom-template-tags/

        if "gizmo_dependencies_loaded" not in context.render_context:
            self.load_gizmos(context)

        # Create markup tags
        tags = []

        if self.output_type == MODALS_OUTPUT_TYPE:
            for dependency in context.render_context["gizmo_modals_list"]:
                tags.append(dependency)

        if self.output_type == CSS_GLOBAL_OUTPUT_TYPE or self.output_type is None:
            for dependency in context.render_context["gizmo_global_css_list"]:
                tags.append('<link href="{0}" rel="stylesheet" />'.format(dependency))

        if self.output_type == CSS_OUTPUT_TYPE or self.output_type is None:
            for dependency in context.render_context["gizmo_css_list"]:
                tags.append('<link href="{0}" rel="stylesheet" />'.format(dependency))

        if self.output_type == JS_GLOBAL_OUTPUT_TYPE or self.output_type is None:
            for dependency in context.render_context["gizmo_global_js_list"]:
                if dependency.endswith("plotly-load_from_python.js"):
                    tags.append(
                        "".join(
                            [
                                '<script type="text/javascript">',
                                get_plotlyjs(),
                                "</script>",
                            ]
                        )
                    )
                else:
                    tags.append(
                        '<script src="{0}" type="text/javascript"></script>'.format(
                            dependency
                        )
                    )

        if self.output_type == JS_OUTPUT_TYPE or self.output_type is None:
            for dependency in context.render_context["gizmo_js_list"]:
                tags.append(
                    '<script src="{0}" type="text/javascript"></script>'.format(
                        dependency
                    )
                )

        # Combine all tag
        tags_string = "\n".join(tags)
        return tags_string


@register.tag
def gizmo_dependencies(parser, token):
    """
    Write all gizmo dependencies (Modals, JavaScript and CSS) to HTML.

    Example::

        {% gizmo_dependenceis modals %}
        {% gizmo_dependencies css %}
        {% gizmo_dependencies js %}

        {% gizmo_dependencies global_css %}
        {% gizmo_dependencies global_js %}
    """
    output_type = None

    bits = token.split_contents()
    if len(bits) > 2:
        raise TemplateSyntaxError(
            f'"gizmo_dependencies" takes at most one argument: the type of dependencies to '
            f"output. Must be one of {VALID_OUTPUT_TYPES}"
        )

    elif len(bits) == 2:
        output_type = bits[1]

    # Validate output_type
    if output_type:
        # Remove quotes and lowercase
        output_type = output_type.strip('"').strip("'").lower()

        # Check for valid values
        if output_type not in VALID_OUTPUT_TYPES:
            raise TemplateSyntaxError(
                f'Invalid output type specified: "{output_type}" as given, '
                f"but must be one of {VALID_OUTPUT_TYPES}"
            )

    return TethysGizmoDependenciesNode(output_type)
