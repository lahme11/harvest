from .services import basket_count


def basket(request):
    return {'basket_count': basket_count(request.user)}
