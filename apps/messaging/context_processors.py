from .services import unread_count


def unread_messages(request):
    return {'unread_message_count': unread_count(request.user)}
