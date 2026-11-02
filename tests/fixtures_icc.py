"""Perfis ICC sintéticos para os testes de fidelidade (sem arquivos binários no repositório)."""
import io
import struct

from PIL import ImageCms


def srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def swapped_primaries_profile_bytes() -> bytes:
    """sRGB com as primárias vermelha e verde trocadas: (255, 0, 0) neste perfil é o verde do sRGB."""
    data = bytearray(srgb_profile_bytes())
    count = struct.unpack('>I', data[128:132])[0]
    tags = {}
    for index in range(count):
        signature, offset, size = struct.unpack('>4sII', data[132 + index * 12:144 + index * 12])
        tags[signature] = (offset, size)
    red, green = tags[b'rXYZ'], tags[b'gXYZ']
    red_data = bytes(data[red[0]:red[0] + red[1]])
    green_data = bytes(data[green[0]:green[0] + green[1]])
    data[red[0]:red[0] + red[1]] = green_data
    data[green[0]:green[0] + green[1]] = red_data
    return bytes(data)


def usable(profile: bytes) -> bool:
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(profile)).profile.xcolor_space.strip() == 'RGB'
    except Exception:
        return False
