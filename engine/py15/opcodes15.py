"""Python 1.5 opcode numbers, and the comparison table COMPARE_OP indexes.

An opcode at or above HAVE_ARGUMENT is followed by a 16-bit little-endian
argument; the others are one byte. Python 1.5 has no EXTENDED_ARG.
"""

HAVE_ARGUMENT = 90

NAMES = {
    0: "STOP_CODE", 1: "POP_TOP", 2: "ROT_TWO", 3: "ROT_THREE", 4: "DUP_TOP",
    10: "UNARY_POSITIVE", 11: "UNARY_NEGATIVE", 12: "UNARY_NOT",
    13: "UNARY_CONVERT", 15: "UNARY_INVERT",
    19: "BINARY_POWER", 20: "BINARY_MULTIPLY", 21: "BINARY_DIVIDE",
    22: "BINARY_MODULO", 23: "BINARY_ADD", 24: "BINARY_SUBTRACT",
    25: "BINARY_SUBSCR",
    30: "SLICE_0", 31: "SLICE_1", 32: "SLICE_2", 33: "SLICE_3",
    40: "STORE_SLICE_0", 41: "STORE_SLICE_1", 42: "STORE_SLICE_2",
    43: "STORE_SLICE_3",
    50: "DELETE_SLICE_0", 51: "DELETE_SLICE_1", 52: "DELETE_SLICE_2",
    53: "DELETE_SLICE_3",
    60: "STORE_SUBSCR", 61: "DELETE_SUBSCR",
    62: "BINARY_LSHIFT", 63: "BINARY_RSHIFT", 64: "BINARY_AND",
    65: "BINARY_XOR", 66: "BINARY_OR",
    70: "PRINT_EXPR", 71: "PRINT_ITEM", 72: "PRINT_NEWLINE",
    80: "BREAK_LOOP", 82: "LOAD_LOCALS", 83: "RETURN_VALUE", 85: "EXEC_STMT",
    87: "POP_BLOCK", 88: "END_FINALLY", 89: "BUILD_CLASS",
    90: "STORE_NAME", 91: "DELETE_NAME", 92: "UNPACK_TUPLE", 93: "UNPACK_LIST",
    95: "STORE_ATTR", 96: "DELETE_ATTR", 97: "STORE_GLOBAL",
    98: "DELETE_GLOBAL",
    100: "LOAD_CONST", 101: "LOAD_NAME", 102: "BUILD_TUPLE", 103: "BUILD_LIST",
    104: "BUILD_MAP", 105: "LOAD_ATTR", 106: "COMPARE_OP", 107: "IMPORT_NAME",
    108: "IMPORT_FROM",
    110: "JUMP_FORWARD", 111: "JUMP_IF_FALSE", 112: "JUMP_IF_TRUE",
    113: "JUMP_ABSOLUTE", 114: "FOR_LOOP", 116: "LOAD_GLOBAL",
    120: "SETUP_LOOP", 121: "SETUP_EXCEPT", 122: "SETUP_FINALLY",
    124: "LOAD_FAST", 125: "STORE_FAST", 126: "DELETE_FAST", 127: "SET_LINENO",
    130: "RAISE_VARARGS", 131: "CALL_FUNCTION", 132: "MAKE_FUNCTION",
    133: "BUILD_SLICE",
}

# COMPARE_OP's argument indexes this. 10 ("exception match") only ever
# appears inside an except clause, which the lifter refuses anyway.
COMPARE = ("<", "<=", "==", "!=", ">", ">=", "in", "not in", "is", "is not",
           "exception match", "BAD")

# Code-object flags (Include/compile.h, 1.5).
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008
