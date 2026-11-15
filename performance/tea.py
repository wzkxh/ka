def encrypt( v0, v1, k0, k1, k2, k3 ):
  sum = 0
  delta = 2654433769
  n = 32
  while n > 0:
    sum = (sum + delta) & 4294967295
    v0 = ( v0 + (((v1 << 4) + k0) ^ (v1 + sum) ^ ((v1 >> 5) + k1))) & 4294967295
    v1 = ( v1 + (((v0 << 4) + k2) ^ (v0 + sum) ^ ((v0 >> 5) + k3))) & 4294967295
    n = n - 1
  return v0

def decrypt(v0, v1, k0, k1, k2, k3):
  sum = 3337565984
  delta = 2654433769
  n = 32
  while n > 0:
    v1 = ( v1 - (((v0 << 4) + k2) ^ (v0 + sum) ^ ((v0 >> 5) + k3))) & 4294967295
    v0 = ( v0 - (((v1 << 4) + k0) ^ (v1 + sum) ^ ((v1 >> 5) + k1))) & 4294967295
    sum = (sum - delta) & 4294967295
    n = n - 1
  return v0

def main():
  k0, k1, k2, k3 = 11, 22, 33, 44
  base_v0, base_v1 = 123456, 789012

  i = 0
  matches = 0
  while i < 30000:
    v0 = (base_v0 + i) & 4294967295
    v1 = (base_v1 + i) & 4294967295

    encrypted = encrypt(v0, v1, k0, k1, k2, k3)
    decrypted = decrypt(encrypted, v1, k0, k1, k2, k3)

    if decrypted == v0:
      matches = matches + 1

    i = i + 1

  print(matches)

main()
