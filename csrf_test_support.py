"""Browser-like form helpers: fetch a real token, never disable CSRF checks."""
from html.parser import HTMLParser


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = dict(attrs, inputs=[])
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None:
            self.current['inputs'].append(attrs)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


def token_from_page(client, path='/login'):
    response = client.get(path)
    if response.status_code != 200:
        raise AssertionError('Could not load CSRF form')
    for form in Forms(response.text).forms:
        for field in form['inputs']:
            if field.get('name') == 'csrf_token':
                return field['value']
    raise AssertionError('Missing CSRF form field')


def csrf_post(client, path, data=None, **kwargs):
    fields = dict(data or {})
    fields['csrf_token'] = token_from_page(client)
    return client.post(path, data=fields, **kwargs)
