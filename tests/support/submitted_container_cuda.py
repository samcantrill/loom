"""Tiny real CUDA-driver computation for opt-in container acceptance."""

import ctypes as c
import os
from uuid import UUID


def compute():
    driver = c.CDLL("libcuda.so.1")

    def call(name, *args):
        result = getattr(driver, name)(*args)
        if result:
            raise RuntimeError(f"{name} failed with CUDA status {result}")

    call("cuInit", 0)
    count, device = c.c_int(), c.c_int()
    call("cuDeviceGetCount", c.byref(count))
    assert count.value == 1, "the granted workload must see exactly one GPU"
    call("cuDeviceGet", c.byref(device), 0)
    identifier = (c.c_ubyte * 16)()
    call("cuDeviceGetUuid", c.byref(identifier), device)
    gpu_uuid = "GPU-" + str(UUID(bytes=bytes(identifier)))
    assert os.environ["CUDA_VISIBLE_DEVICES"] == gpu_uuid
    context, module, kernel = c.c_void_p(), c.c_void_p(), c.c_void_p()
    address = c.c_uint64()
    call("cuCtxCreate_v2", c.byref(context), 0, device)
    try:
        # Each thread writes its squared index; four small outputs prove compute.
        ptx = b"""
.version 6.0
.target sm_52
.address_size 64
.visible .entry squares(.param .u64 output) {
    .reg .b32 %r<3>;
    .reg .b64 %rd<4>;
    ld.param.u64 %rd1, [output];
    mov.u32 %r1, %tid.x;
    mul.lo.u32 %r2, %r1, %r1;
    mul.wide.u32 %rd2, %r1, 4;
    add.u64 %rd3, %rd1, %rd2;
    st.global.u32 [%rd3], %r2;
    ret;
}
"""
        call("cuModuleLoadData", c.byref(module), c.c_char_p(ptx))
        call("cuModuleGetFunction", c.byref(kernel), module, c.c_char_p(b"squares"))
        call("cuMemAlloc_v2", c.byref(address), c.c_size_t(16))
        parameters = (c.c_void_p * 1)(c.addressof(address))
        call("cuLaunchKernel", kernel, 1, 1, 1, 4, 1, 1, 0, c.c_void_p(), parameters, c.c_void_p())
        call("cuCtxSynchronize")
        values = (c.c_uint32 * 4)()
        call("cuMemcpyDtoH_v2", values, address, c.c_size_t(16))
        assert list(values) == [0, 1, 4, 9]
        return {"device_count": count.value, "device_uuid": gpu_uuid, "values": list(values)}
    finally:
        if address.value:
            call("cuMemFree_v2", address)
        if module.value:
            call("cuModuleUnload", module)
        call("cuCtxDestroy_v2", context)
