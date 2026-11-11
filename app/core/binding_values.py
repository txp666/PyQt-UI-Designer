"""Conversions shared by live bindings and standalone exported applications."""
import ast
from functools import lru_cache
import math
import operator
import struct

from .i18n import tr


_EXPRESSION_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Name,
    ast.Load, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
    ast.Invert, ast.Not, ast.UAdd, ast.USub, ast.And, ast.Or, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


@lru_cache(maxsize=256)
def _curve_expression_code(expression):
    # Cache rejected expressions too: malformed project text is received on every sample.
    try:
        if len(expression) > 4096:
            return None
        tree = ast.parse(expression.strip(), mode="eval")
        nodes = list(ast.walk(tree))
        if len(nodes) > 512:
            return None
        for node in nodes:
            if not isinstance(node, _EXPRESSION_NODES):
                return None
            if isinstance(node, ast.Name) and node.id != "value":
                return None
            if isinstance(node, ast.Constant) and type(node.value) not in (int, float, bool):
                return None
        return tree.body
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None


def _expression_number(value):
    if type(value) not in (int, float, bool):
        raise ValueError("Expression requires a real number")
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise OverflowError("Expression integer exceeds 64 bits")
    elif not math.isfinite(value):
        raise ValueError("Expression requires a finite number")
    return value


_EXPRESSION_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
}
_EXPRESSION_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


def _expression_eval(node, value):
    if isinstance(node, ast.Constant):
        return _expression_number(node.value)
    if isinstance(node, ast.Name):
        return _expression_number(value)
    if isinstance(node, ast.BoolOp):
        for child in node.values:
            result = _expression_eval(child, value)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _expression_eval(node.left, value)
        for op, child in zip(node.ops, node.comparators):
            right = _expression_eval(child, value)
            if not _EXPRESSION_COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.UnaryOp):
        operand = _expression_eval(node.operand, value)
        operation = {ast.UAdd: operator.pos, ast.USub: operator.neg,
                     ast.Not: operator.not_, ast.Invert: operator.invert}[type(node.op)]
        return _expression_number(operation(operand))
    left = _expression_eval(node.left, value)
    right = _expression_eval(node.right, value)
    if isinstance(node.op, (ast.LShift, ast.RShift)):
        if not isinstance(left, int) or not isinstance(right, int) or right < 0:
            raise ValueError("Invalid shift")
        if isinstance(node.op, ast.RShift):
            result = left >> min(right, 63)
        elif left == 0:
            result = 0
        elif right >= 64:
            raise OverflowError("Left shift exceeds 64 bits")
        else:
            result = left << right  # At most 127 bits before the range check.
    elif isinstance(node.op, ast.Pow):
        if isinstance(left, int) and isinstance(right, int) and right >= 0:
            if left in (-1, 0, 1):
                result = 1 if right == 0 else (left if left != -1 or right % 2 else 1)
            elif right > 63:
                raise OverflowError("Integer power exceeds 64 bits")
            else:
                # Each multiplication has two 64-bit operands; stop before the next step.
                result = 1
                for _ in range(right):
                    result = _expression_number(result * left)
        else:
            result = math.pow(left, right)
    else:
        result = _EXPRESSION_BINARY[type(node.op)](left, right)
    return _expression_number(result)


def curve_expression(raw_value, expression):
    """Evaluate bounded numeric curve arithmetic; failures preserve the original numeric input."""
    if not expression:
        return raw_value
    if isinstance(raw_value, str):
        raw_value = binding_float(raw_value)
    else:
        binding_float(raw_value)
    try:
        node = _curve_expression_code(expression)
        return _expression_eval(node, raw_value) if node is not None else raw_value
    except Exception:
        return raw_value


def binding_integer(value):
    """Accept integer-compatible values that fit Qt's signed 32-bit API."""
    number = int(value)
    if not -(2 ** 31) <= number < 2 ** 31:
        raise OverflowError(tr("绑定整数超出 Qt 支持的范围"))
    return number


def binding_float(value):
    """Reject NaN/infinity before passing a sample to a numeric widget."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(tr("绑定数值必须是有限数"))
    return number


def binding_register(value):
    """Modbus register payloads must be unsigned 16-bit integers."""
    if not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError(tr("Modbus 寄存器值必须是 0 到 65535 的整数"))
    return value


# Where a Modbus binding or chart curve reads: a register table, whose registers a reply names by
# address (hr100), from the request it answers. 保持寄存器 when a binding names none.
MODBUS_AREAS = {"保持寄存器": "hr", "输入寄存器": "ir", "线圈": "co", "离散输入": "di"}  # i18n: value
DEFAULT_MODBUS_AREA = "保持寄存器"  # i18n: value
# The registers a value of each type takes; coils and discrete inputs are one bit each.
MODBUS_REGISTERS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


def modbus_need(area, address, data_type="uint16", slave_filter=-1, period=0):
    """What a Modbus binding or chart curve reads, for the Modbus poller:
    ``(slave, table, address, count, period)``, or None for an area that is not a register table.
    A slave of 0 or less stands for the poller's default slave, a period of 0 for its default period."""
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    count = 1 if table in ("co", "di") else MODBUS_REGISTERS.get(data_type, 1)
    return int(slave_filter), table, int(address), count, max(0, min(60000, int(period)))


def modbus_value(data, address, data_type="uint16", reg_order="大端(AB CD)",  # i18n: value
                 fc_filter=-1, slave_filter=-1, area=DEFAULT_MODBUS_AREA):
    """One value from a parsed Modbus response, or None when the response does not hold it.

    The value is the register (or coil, or discrete input) at ``address`` of the area's table,
    named by address in a reply to a read this program sent (hr100, co3). 32-bit types take the
    register at the address and the next one, which must be in the same response. Coils and
    discrete inputs are 0 or 1 whatever the data type.
    """
    if slave_filter >= 0 and data.get("slave") != slave_filter:
        return None
    fc = data.get("fc", 0)
    if fc_filter >= 0 and fc != fc_filter:
        return None
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    if table in ("co", "di"):
        return data.get(f"{table}{address}")
    r0 = data.get(f"{table}{address}")
    if r0 is None:
        return None
    r0 = binding_register(r0)
    if data_type == "uint16":
        return r0
    if data_type == "int16":
        return r0 - 65536 if r0 > 32767 else r0
    r1 = data.get(f"{table}{address + 1}")
    if r1 is None:
        return None
    r1 = binding_register(r1)
    high, low = (r0, r1) if reg_order == "大端(AB CD)" else (r1, r0)  # i18n: value
    raw = high.to_bytes(2, "big") + low.to_bytes(2, "big")
    if data_type == "uint32":
        return int.from_bytes(raw, "big")
    if data_type == "int32":
        return int.from_bytes(raw, "big", signed=True)
    if data_type == "float32":
        return struct.unpack(">f", raw)[0]
    return r0


def binding_boolean(value):
    """Read explicit boolean tokens or finite numbers; reject unknown text."""
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in ("true", "on", "yes"):
            return True
        if token in ("false", "off", "no"):
            return False
    return bool(binding_float(value))


def binding_decimals(value, places="自动"):  # i18n: value
    """A number shown with a fixed count of decimal places; anything else (text, flags, NaN) as it came."""
    if places in ("自动", "", None) or isinstance(value, bool):  # i18n: value
        if isinstance(value, float) and math.isfinite(value):
            # 15 significant digits: the noise of binary arithmetic (267 * 0.1 = 26.700000000000003)
            # goes, every digit a double really holds stays.
            return float(f"{value:.15g}")
        return value
    try:
        number = float(value)
        places = int(places)
    except (TypeError, ValueError, OverflowError):
        return value
    if not math.isfinite(number):
        return value
    return f"{number:.{places}f}"


def binding_led(value, on_value="1", off_value="0"):
    """Preserve custom LED states before falling back to boolean conversion."""
    text = str(value).strip()
    if text == on_value:
        return True
    if text == off_value:
        return False
    try:
        return binding_float(value) == binding_float(on_value)
    except (TypeError, ValueError, OverflowError):
        return binding_boolean(value)
