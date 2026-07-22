from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)

plain_password = "changethis"
stored_hash = "$argon2id$v=19$m=65536,t=3,p=4$6w7x9fxM+NVbNBq8t3tUNA$V+Pxxga/+4yl5GOZReF8kF16WdHn+GQM0GNhxoKEmmI"

if password_hash.verify(plain_password, stored_hash):
    print("Password is correct")
else:
    print("Invalid password")