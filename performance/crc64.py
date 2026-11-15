MASK = 0xFFFFFFFFFFFFFFFF
POLY = 0x42F0E1EBA9EA3693          # CRC-64 (ECMA)

def crc64_update(crc,value):
  """Feed one 64-bit value into the CRC (bit by bit)."""
  crc = (crc^value) & MASK
  i = 0
  while i < 64:
    if (crc & 0x8000000000000000) != 0:
      crc = ((crc << 1) ^ POLY) & MASK
    else:
      crc = (crc << 1) & MASK
    i = i + 1
  return crc

def checksum(n):
  """CRC-64 of the integers 0 .. n-1."""
  crc = 0
  i = 0
  while i < n:
    crc = crc64_update(crc,i)
    i = i + 1
  return crc

def main():
  N = 500_000     # raise this for longer benchmarks
  h = checksum(N)
  print(h>>1)     # 6380114920827571293 5.235

main()

'''
Real ECMA-182 for bytes:
# https://github.com/futekast/CRC64_ECMA

def crc64_update(crc,value):
  crc = (crc^(value<<56)) & MASK
  i = 0
  while i < 8:
    if (crc & 0x8000000000000000) != 0:
      crc = ((crc << 1) ^ POLY) & MASK
    else:
      crc = (crc << 1) & MASK
    i = i + 1
  return crc

def main():
  crc = 0
  for c in '123456789':
    o = ord(c)
    crc = crc64_update(crc,o)
  print("%x"%crc) # 6c40df5f0b497347

main()
'''
