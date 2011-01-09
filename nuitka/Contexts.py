#
#     Copyright 2010, Kay Hayen, mailto:kayhayen@gmx.de
#
#     Part of "Nuitka", an attempt of building an optimizing Python compiler
#     that is compatible and integrates with CPython, but also works on its
#     own.
#
#     If you submit Kay Hayen patches to this software in either form, you
#     automatically grant him a copyright assignment to the code, or in the
#     alternative a BSD license to the code, should your jurisdiction prevent
#     this. Obviously it won't affect code that comes to him indirectly or
#     code you don't submit to him.
#
#     This is to reserve my ability to re-license the code at any time, e.g.
#     the PSF. With this version of Nuitka, using it for Closed Source will
#     not be allowed.
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, version 3 of the License.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#     Please leave the whole of this copyright notice intact.
#
""" Code generation contexts.

"""

# pylint: disable=W0622
from .__past__ import long, unicode, cpickle
# pylint: enable=W0622

import pickle, math

from .Identifiers import namifyConstant, Identifier, ConstantIdentifier, LocalVariableIdentifier, ClosureVariableIdentifier
from .CppRawStrings import encodeString

# TODO: Shouldn't be here, the related code like belongs to Generator instead.
from . import CodeTemplates

from logging import warning

class Constant:
    def __init__( self, constant ):
        self.constant = constant

        try:
            self.hash = hash( constant )
        except TypeError:
            self.hash = 55

    def getConstant( self ):
        return self.constant

    def __hash__( self ):
        return self.hash

    def __eq__( self, other ):
        assert isinstance( other, self.__class__ )

        return type( self.constant ) is type( other.constant ) and _compareConstants( self.constant, other.constant ) and repr( self.constant ) == repr( other.constant )

class PythonContextBase:
    def __init__( self ):
        self.variables = set()

        self.while_loop_count = 0
        self.for_loop_count = 0

        self.try_count = 0
        self.with_count = 0

        self.temp_counter = 0

    def allocateForLoopNumber( self ):
        self.for_loop_count += 1

        return self.for_loop_count

    def allocateWhileLoopNumber( self ):
        self.while_loop_count += 1

        return self.while_loop_count

    def allocateTryNumber( self ):
        self.try_count += 1

        return self.try_count

    def allocateWithNumber( self ):
        self.with_count += 1

        return self.with_count

    def addVariable( self, var_name ):
        self.variables.add( var_name )

    def isClosureViaContext( self ):
        return True

    def isParametersViaContext( self ):
        return False

    def getTempObjectVariable( self ):
        # TODO: Make sure these are actually indepedent in generated code between
        # different contexts

        result = Identifier( "_expression_temps[%d] " % self.temp_counter, 0 )

        self.temp_counter += 1

        return result

    def hasLocalsDict( self ):
        return False

class PythonChildContextBase( PythonContextBase ):
    def __init__( self, parent ):
        PythonContextBase.__init__( self )

        self.parent = parent

    def getParent( self ):
        return self.parent

    def getConstantHandle( self, constant ):
        return self.parent.getConstantHandle( constant )

    def addContractionCodes( self, contraction, contraction_identifier, contraction_context, contraction_code, loop_var_codes, contraction_conditions, contraction_iterateds ):
        return self.parent.addContractionCodes( contraction, contraction_identifier, contraction_context, contraction_code, loop_var_codes, contraction_conditions, contraction_iterateds )

    def addLambdaCodes( self, lambda_def, lambda_code, lambda_context ):
        self.parent.addLambdaCodes( lambda_def, lambda_code, lambda_context )

    def addGlobalVariableNameUsage( self, var_name ):
        self.parent.addGlobalVariableNameUsage( var_name )

    def getModuleCodeName( self ):
        return self.parent.getModuleCodeName()

    def getModuleName( self ):
        return self.parent.getModuleName()


def _compareConstants( a, b ):
    # Supposed fast path for comparison.
    if type( a ) is not type( b ):
        return False

    # The NaN values of float and complex may let this fail, even if the constants are
    # built in the same way.
    if a == b:
        return True

    # Now it's either not the same, or it is a container that contains NaN or it is a
    # complex or float that is NaN.
    if type( a ) is complex:
        return _compareConstants( a.imag, b.imag ) and _compareConstants( a.real, b.real )

    if type( a ) is float:
        return math.isnan( a ) and math.isnan( b )

    if type( a ) in ( tuple, list ):
        if len( a ) != len( b ):
            return False

        for ea, eb in zip( a, b ):
            if not _compareConstants( ea, eb ):
                return False
        else:
            return True

    if type( a ) is dict:
        for ea1, ea2 in a.iteritems():
            for eb1, eb2 in b.iteritems():
                if _compareConstants( ea1, eb1 ) and _compareConstants( ea2, eb2 ):
                    break
            else:
                return False
        else:
            return True

    if type( a ) in ( frozenset, set ):
        if len( a ) != len( b ):
            return False

        for ea in a:
            if ea not in b:
                # Due to NaN values, we need to compare each set element with all the
                # other set to be really sure.
                for eb in b:
                    if _compareConstants( ea, eb ):
                        break
                else:
                    return False
        else:
            return True

    return False


def _getConstantHandle( constant ):
    constant_type = type( constant )

    if constant_type in ( int, long, str, unicode, float, bool, complex, tuple, list, dict, frozenset ):
        return "_python_" + namifyConstant( constant )
    elif constant is Ellipsis:
        return "Py_Ellipsis"
    else:
        raise Exception( "Unknown type for constant handle", type( constant ), constant  )

class PythonGlobalContext:
    def __init__( self ):
        self.constants = {}

        self.const_tuple_empty  = self.getConstantHandle( () ).getCode()
        self.const_string_empty = self.getConstantHandle( "" ).getCode()
        self.const_bool_true    = self.getConstantHandle( True ).getCode()
        self.const_bool_false   = self.getConstantHandle( False ).getCode()

        self.module_name__      = self.getConstantHandle( "__module__" ).getCode()
        self.class__            = self.getConstantHandle( "__class__" ).getCode()
        self.dict__             = self.getConstantHandle( "__dict__" ).getCode()
        self.doc__              = self.getConstantHandle( "__doc__" ).getCode()
        self.file__             = self.getConstantHandle( "__file__" ).getCode()
        self.enter__            = self.getConstantHandle( "__enter__" ).getCode()
        self.exit__             = self.getConstantHandle( "__exit__" ).getCode()

    def getConstantHandle( self, constant ):
        if constant is None:
            return Identifier( "Py_None", 0 )
        elif constant is Ellipsis:
            return Identifier( "Py_Ellipsis", 0 )
        else:
            key = ( type( constant ), repr( constant ), Constant( constant ) )

            if key not in self.constants:
                self.constants[ key ] = _getConstantHandle( constant )

            return ConstantIdentifier( self.constants[ key ] )

    def getConstantCode( self ):
        return CodeTemplates.constant_reading % {
            "const_init"         : self.getConstantInitializations(),
            "const_declarations" : self.getConstantDeclarations( for_header = False ),
        }

    def getConstantDeclarations( self, for_header ):
        statements = []

        for constant_name in sorted( self.constants.values()  ):
            if for_header:
                declaration = "extern PyObject *%s;" % constant_name
            else:
                declaration = "PyObject *%s;" % constant_name

            statements.append( declaration )

        return "\n".join( statements )

    def getConstantInitializations( self ):
        statements = []

        for constant_desc, constant_identifier in sorted( self.constants.items(), key = lambda x: x[1] ):
            constant_type, _constant_repr, constant_value = constant_desc
            constant_value = constant_value.getConstant()

            # Use shortest code for ints, except when they are big, then fall fallback to
            # pickling.
            if constant_type == int and abs( constant_value ) < 2**31:

                statements.append(
                    "%s = PyInt_FromLong( %s );" % (
                        constant_identifier,
                        constant_value )
                    )

                continue

            # Note: The "str" should not be necessary, but I had an apparent g++ bug that
            # prevented it from working correctly, where UNSTREAM_STRING would return NULL
            # even when it asserts against that.
            if constant_type in ( str, tuple, list, bool, float, complex, unicode, int, long, dict, frozenset, set ):
                # Note: The marshal module cannot persist all unicode strings and
                # therefore cannot be used.  The cPickle fails to gives reproducible
                # results for some tuples, which needs clarification. In the mean time we
                # are using pickle.
                try:
                    saved = pickle.dumps(
                        constant_value,
                        protocol = 0 if constant_type is unicode else 0
                    )
                except TypeError:
                    warning( "Problem with persisting constant '%r'." % constant_value )
                    raise

                # Check that the constant is restored correctly.
                restored = cpickle.loads( saved )

                assert _compareConstants( restored, constant_value ), ( repr( constant_value ), "!=", repr( restored ) )

                if str is unicode:
                    saved = saved.decode( "utf_8" )

                statements.append( "%s = UNSTREAM_CONSTANT( %s, %d );" % (
                    constant_identifier,
                    encodeString( saved ),
                    len( saved ) )
                )
            elif constant_type is str:
                statements.append(
                    "%s = UNSTREAM_STRING( %s, %d );" % (
                        constant_identifier,
                        encodeString( constant_value ),
                        len(constant_value)
                    )
                )
            elif constant_value is None:
                pass
            else:
                assert False, (type(constant_value), constant_value, constant_identifier)


        return "\n        ".join( statements )

class PythonPackageContext( PythonContextBase ):
    def __init__( self, package_name, global_context ):
        PythonContextBase.__init__( self )

        self.package_name = package_name

        self.global_context = global_context

        self.global_var_names = set()

    def getConstantHandle( self, constant ):
        return self.global_context.getConstantHandle( constant )

    def getGlobalVariableNames( self ):
        return self.global_var_names


class PythonModuleContext( PythonContextBase ):
    def __init__( self, module_name, code_name, filename, global_context ):
        PythonContextBase.__init__( self )

        self.name = module_name
        self.code_name = code_name
        self.filename = filename

        self.global_context = global_context
        self.functions = {}

        self.class_codes = {}
        self.function_codes = []
        self.lambda_codes = []
        self.contraction_codes = []

        self.lambda_count = 0

        self.global_var_names = set()

    def __repr__( self ):
        return "<PythonModuleContext instance for module %s>" % self.filename

    def getParent( self ):
        return None

    def getConstantHandle( self, constant ):
        return self.global_context.getConstantHandle( constant )

    def addFunctionCodes( self, function, function_context, function_codes ):
        self.function_codes.append( ( function, function_context, function_codes ) )

    def addClassCodes( self, class_def, class_context, class_codes ):
        assert class_def not in self.class_codes

        self.class_codes[ class_def ] = ( class_context, class_codes )

    def addLambdaCodes( self, lambda_def, lambda_code, lambda_context ):
        self.lambda_codes.append( ( lambda_def, lambda_code, lambda_context ) )

    def addContractionCodes( self, contraction, contraction_identifier, contraction_context, contraction_code, loop_var_codes, contraction_conditions, contraction_iterateds ):
        self.contraction_codes.append( ( contraction, contraction_identifier, contraction_context, loop_var_codes, contraction_code, contraction_conditions, contraction_iterateds ) )

    def getContractionsCodes( self ):
        return self.contraction_codes

    def getFunctionsCodes( self ):
        return self.function_codes

    def getClassesCodes( self ):
        return self.class_codes

    def getLambdasCodes( self ):
        return self.lambda_codes

    def getGeneratorExpressionCodeHandle( self, generator_def ):
        generator_name = generator_def.getFullName()

        return "_python_generatorfunction_" + generator_name

    def allocateLambdaIdentifier( self ):
        self.lambda_count += 1

        return "_python_modulelambda_%d_%s" % ( self.lambda_count, self.getName() )

    def getName( self ):
        return self.name

    getModuleName = getName

    def getModuleCodeName( self ):
        return self.getCodeName()

    # There cannot ne local variable in modules no need to consider the name.
    # pylint: disable=W0613
    def hasLocalVariable( self, var_name ):
        return False

    def hasClosureVariable( self, var_name ):
        return False
    # pylint: enable=W0613

    def canHaveLocalVariables( self ):
        return False

    def addGlobalVariableNameUsage( self, var_name ):
        self.global_var_names.add( var_name )

    def getGlobalVariableNames( self ):
        return self.global_var_names

    def getCodeName( self ):
        return self.code_name

    def getTracebackName( self ):
        return "<module>"

    def getTracebackFilename( self ):
        return self.filename



class PythonFunctionContext( PythonChildContextBase ):
    def __init__( self, parent, function ):
        PythonChildContextBase.__init__( self, parent = parent )

        self.function = function

        self.lambda_count = 0

        # Make sure the local names are available as constants
        for local_name in function.getLocalVariableNames():
            self.getConstantHandle( constant = local_name )

    def __repr__( self ):
        return "<PythonFunctionContext for function '%s'>" % self.function.getName()

    def hasLocalsDict( self ):
        return self.function.hasLocalsDict()

    def hasLocalVariable( self, var_name ):
        return var_name in self.function.getLocalVariableNames()

    def hasClosureVariable( self, var_name ):
        return var_name in self.function.getClosureVariableNames()

    def canHaveLocalVariables( self ):
        return True

    def isParametersViaContext( self ):
        return self.function.isGenerator()

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name, from_context = self.function.isGenerator() )

    def getClosureHandle( self, var_name ):
        if not self.function.isGenerator():
            return ClosureVariableIdentifier( var_name, from_context = "_python_context->" )
        else:
            return ClosureVariableIdentifier( var_name, from_context = "_python_context->common_context->" )

    def getDefaultHandle( self, var_name ):
        return Identifier( "_python_context->default_value_" + var_name, 0 )

    def getLambdaExpressionCodeHandle( self, lambda_expression ):
        return self.parent.getLambdaExpressionCodeHandle( lambda_expression = lambda_expression )

    def getGeneratorExpressionCodeHandle( self, generator_def ):
        return self.parent.getGeneratorExpressionCodeHandle( generator_def = generator_def )

    def allocateLambdaIdentifier( self ):
        self.lambda_count += 1

        return "_python_lambda_%d_%s" % ( self.lambda_count, self.function.getFullName() )

    def addFunctionCodes( self, function, function_context, function_codes ):
        self.parent.addFunctionCodes( function, function_context, function_codes )

    def addClassCodes( self, class_def, class_context, class_codes ):
        self.parent.addClassCodes( class_def, class_context, class_codes )

    def getCodeName( self ):
        return self.function.getCodeName()

    def getTracebackName( self ):
        return self.function.getName()

    def getTracebackFilename( self ):
        # TODO: Memoize would do wonders for these things mayhaps.
        return self.function.getParentModule().getFilename()


class PythonContractionBase( PythonChildContextBase ):
    def __init__( self, parent, loop_variables, leak_loop_vars ):
        PythonChildContextBase.__init__( self, parent = parent )

        self.loop_variables = tuple( loop_variables )
        self.leak_loop_vars = leak_loop_vars

    def isClosureViaContext( self ):
        return False

    def isGeneratorExpression( self ):
        return self.__class__ == PythonGeneratorExpressionContext

class PythonListContractionContext( PythonContractionBase ):
    def __init__( self, parent, loop_variables ):
        PythonContractionBase.__init__(
            self,
            parent         = parent,
            loop_variables = loop_variables,
            leak_loop_vars = True
        )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "" )

    def getLocalHandle( self, var_name ):
        return self.getClosureHandle( var_name )

class PythonGeneratorExpressionContext( PythonContractionBase ):
    def __init__( self, parent, loop_variables ):
        PythonContractionBase.__init__(
            self,
            parent         = parent,
            loop_variables = loop_variables,
            leak_loop_vars = False
        )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "_python_context->" )

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name, from_context = True )

class PythonSetContractionContext( PythonContractionBase ):
    def __init__( self, parent, loop_variables ):
        PythonContractionBase.__init__(
            self,
            parent         = parent,
            loop_variables = loop_variables,
            leak_loop_vars = False
        )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "" )

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name, from_context = False )


class PythonDictContractionContext( PythonContractionBase ):
    def __init__( self, parent, loop_variables ):
        PythonContractionBase.__init__(
            self,
            parent         = parent,
            loop_variables = loop_variables,
            leak_loop_vars = False
        )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "" )

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name, from_context = False )


class PythonLambdaExpressionContext( PythonChildContextBase ):
    def __init__( self, parent, parameter_names ):
        PythonChildContextBase.__init__( self, parent = parent )

        self.parameter_names = parameter_names

        # Make sure the parameter names are available as constants
        for parameter_name in parameter_names:
            self.getConstantHandle( constant = parameter_name )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "_python_context->" )

    def hasLocalVariable( self, var_name ):
        return var_name in self.parameter_names

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name )

    def getDefaultHandle( self, var_name ):
        return Identifier( "_python_context->default_value_" + var_name, 0 )

class PythonClassContext( PythonChildContextBase ):
    def __init__( self, parent, class_def ):
        PythonChildContextBase.__init__( self, parent = parent )

        self.class_def = class_def

    def hasLocalVariable( self, var_name ):
        return var_name in self.class_def.getClassVariableNames()

    def hasClosureVariable( self, var_name ):
        return var_name in self.class_def.getClosureVariableNames()

    def getLocalHandle( self, var_name ):
        return LocalVariableIdentifier( var_name )

    def getClosureHandle( self, var_name ):
        return ClosureVariableIdentifier( var_name, from_context = "" )

    def addFunctionCodes( self, function, function_context, function_codes ):
        self.parent.addFunctionCodes( function, function_context, function_codes )

    def addClassCodes( self, class_def, class_context, class_codes ):
        self.parent.addClassCodes( class_def, class_context, class_codes )

    def isClosureViaContext( self ):
        return False

    def getTracebackName( self ):
        return self.class_def.getName()

    def getTracebackFilename( self ):
        return self.class_def.getParentModule().getFilename()

    def getCodeName( self ):
        return self.class_def.getCodeName()

    def hasLocalsDict( self ):
        return self.class_def.hasLocalsDict()