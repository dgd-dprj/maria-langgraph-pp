// Referência executada para String(n), Number(v) e JSON.stringify do Node 24.
const numeros = [0, -0, 7, -7, 1.5, 0.1, 0.1 + 0.2, 1e-7, 1e-6, 123456789, 1e20, 1e21, 1.7976931348623157e308, 5e-324, 2 ** 53, 2 ** 53 + 2, 12345678901234567890, -1e-7, 123.456, 1e100, 100, 0.000001234];
const textos = ["", "  ", " 5 ", "5", "1e3", "0x10", "0X1f", "0o17", "0b101", "-0x10", "Infinity", "-Infinity", "+Infinity", "abc", "1.", ".5", "+.5", "1e", " 5﻿", "5\x1c", "12px", "0x", "1_000"];
const saida: Record<string, unknown> = {
  string: Object.fromEntries(numeros.map((n) => [String(n), String(n)])),
  stringify: Object.fromEntries(numeros.map((n) => [String(n), JSON.stringify(n)])),
  number: Object.fromEntries(textos.map((t) => [JSON.stringify(t), String(Number(t))])),
  lista: { vazia: String(Number([])), um: String(Number([" 5"])), dois: String(Number([1, 2])), aninhada: String(Number([[3]])) },
};
console.log(JSON.stringify(saida, null, 1));
