def test_internal_server_error():
    from infi.rpc.errors import InternalServerError, RPCException
    from infi.rpc.base.protocol import encode_rpc_result_exc_info
    from sys import exc_info
    try:
        raise Exception()
    except Exception:
        response = encode_rpc_result_exc_info(exc_info(), True)
        RPCException.from_dict(response['exception'])
