import sys, traceback

from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import simplejson
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
from django.core.urlresolvers import reverse
from django.conf.urls.defaults import patterns, url
from django.views.generic.simple import redirect_to
from django.shortcuts import render, render_to_response, get_object_or_404
from django.template import context, loader, RequestContext

from extserializer import jsonDumpStripped

import extforms

from crud import ExtDirectCRUDComplex ,  format_form_errors

class ExtDirectProvider(object):
    """
    Abstract class for different ExtDirect Providers implementations
    """
    
    def __init__(self, type, id=None, url=None, urlname=None):
        self.type = type
        self.id = id

        if not url is None:
            self.url = url
        elif not urlname is None:
            self.urlname = urlname
        else:
            self.url = '/'

    @property
    def baseurl(self):
        if hasattr(self, 'url'):
            return self.url
        elif hasattr(self, 'urlname'):
            return reverse(self.urlname)
        else: return None


    @property
    def _config(self):
        """
        Return the config object to add a new Ext.DirectProvider
        It must allow to be dumped using simplejson.dumps
        """
        raise NotImplementedError
        
    def register(self, **kw):
        """
        Register a new function/method in this Provider.
        The arguments to this function will depend on the subclasses that
        implement it
        """
        raise NotImplementedError
        
    def router(self, request):
        """
        Entry point for ExtDirect requests.
        Subclasses must implement this method and make the rpc call.
        
        You will have to add an urlpattern to your urls.py
        pointing to this method. Something like::
        
            remote_provider = ExtDirectProvider('/some-url/', ...)
            urlpatterns = patterns(
                ...,
                (r'^some-url/$', remote_provider.router),
                ...
            )
        """
        raise NotImplementedError
    
    def script(self, request, template="extdirect/django/script.js"):
        """
        Return a HttpResponse with the javascript code needed
        to register the DirectProvider in Ext.
        
        You will have to add an urlpattern to your urls.py
        pointing to this method. Something like::
        
            remote_provider = ExtDirectProvider('/some-url/', ...)
            urlpatterns = patterns(
                ...,
                (r'^myprovider.js/$', remote_provider.script),
                ...
            )
        """
        config = jsonDumpStripped(self._config)
        js = render(request, template, {'config': config})

        return HttpResponse(js, mimetype='text/javascript')

    def get_urls(self):
        """
        Return the URL patterns.
        """
        urlpatterns =  patterns('',
            (r'^router/$',  self.router ),
            (r'^provider.js$', self.script ),
        )
        if hasattr(self, 'urlname'):
            urlpatterns +=  patterns('',
                url(r'^$', redirect_to, {'url': '/'}, name=self.urlname)
            )
        return urlpatterns
    
class ExtRemotingProvider(ExtDirectProvider):
    """
    ExtDirect RemotingProvider implementation
    """
    
    type = 'remoting'
    
    def __init__(self, namespace, id=None, url=None, urlname=None, descriptor='Descriptor'):
        super(ExtRemotingProvider, self).__init__(self.type, id, url=url, urlname=urlname)
        
        self.namespace = namespace        
        self.actions = {}
        self.descriptor = descriptor


    def api(self, request, template="extdirect/django/api.js"):
        conf = self._config
        descriptor = self.namespace + '.' + self.descriptor
        
        if request.GET.has_key('format') and request.GET['format'] == 'json':
            conf['descriptor'] = descriptor
            mimetype = 'application/json'
            response = jsonDumpStripped(conf)
        else:
            mimetype = 'text/javascript'
            template_vars = {
                'namespace': self.namespace,
                'descriptor': descriptor,
                'config': jsonDumpStripped(self._config), 
            }
            response = render(request, template, template_vars)

        return HttpResponse(response, mimetype=mimetype)
        
    @property
    def _config(self):
        config = {
            'url'       : '%srouter/' % (self.baseurl,),
            'namespace' : self.namespace,
            'type'      : self.type,
            'actions'   : {}                
        }
        
        for action, methods in self.actions.items():
            config['actions'][action] = []
            
            for func, info in methods.items():
                method = dict(name=func, len=info['len'], formHandler=info['form_handler'])
                config['actions'][action].append(method)
        
        if self.id:
            config['id'] = self.id
        
        return config    

    
    def registerCRUD(self, cls,  action = None, app = None ):
        # register CRUD actions for specified cls model
        # the default ExtDirect action will be 'app_label_model_name'
        
        class CrudItem( ExtDirectCRUDComplex ):
            model = cls
            provider = self
            
        item = CrudItem()
        
        if not app:
            app = cls._meta.app_label
        if not action:
            action = '%s_%s' % (app, cls.__name__)
        item.register_actions(self, action , False, None)
        return item
        
    def registerForm(self, formCls,  action = None, name = None, success = None):
        # register submit action for forms
        if not action:
            action = 'forms_%s' % formCls.__name__
        
        def load(request):
            print 'LOAD FORM'
            return {'ok':True}
            
        def submit(request):
            c = formCls(data = request.POST, files = request.FILES)
            if c.is_valid():
                if success and callable(success):
                    success(request, c)
                return {'success':True}
            else:
                return {'success':False, 'errors':format_form_errors(c.errors) }
                
        def getFields(request):
            c = formCls()
            helper = extforms.Form(formInstance = c)
            extfieldsConfig = helper.getFieldsConfig()
            return {'fields':extfieldsConfig}
            
        self.register(load, action = action, name = 'load', form_handler = False)        
        self.register(getFields, action = action, name = 'getFields', len=0, form_handler = False)        
        self.register(submit, action = action, name = 'submit', len=0, form_handler = True)

        
    def register(self, method, action=None, name=None, len=0, form_handler=False, \
                 login_required=False, permission=None):
        
        if not action:
            action = method.__module__.replace('.', '_')
            
        if not self.actions.has_key(action):
            #first time
            self.actions[action] = {}
        
        #if name it's None, we use the real function name.
        name = name or method.__name__  
        self.actions[action][name] = dict(func=method,
                                          len=len,
                                          form_handler=form_handler,
                                          login_required=login_required,
                                          permission=permission)        
        
    def dispatcher(self, request, extdirect_req):
        """
        Parse the ExtDirect specification an call
        the function with the `request` instance.
        
        If the `request` didn't come from an Ext Form, then the
        parameters recieved will be added to the `request` in the
        `extdirect_post_data` attribute.
        """
        
        action = extdirect_req['action']
        method = extdirect_req['method']
        
        func = self.actions[action][method]['func']        
        
        data = None
        if not extdirect_req.get('isForm'):
            data = extdirect_req.pop('data')
        
        #the response object will be the same recieved but without `data`.
        #we will add the `result` later.
        response = extdirect_req
        
        #Checks for login or permissions required
        login_required = self.actions[action][method]['login_required']
        if(login_required):            
            if not request.user.is_authenticated():                
                response['result'] = dict(success=False, message='You must be authenticated to run this method.')
                return response
            
        permission = self.actions[action][method]['permission']
        if(permission):            
            if not request.user.has_perm(permission):                
                response['result'] = dict(success=False, messsage='You need `%s` permission to run this method' % permission)
                return response
        if data:
            #this is a simple hack to convert all the dictionaries keys
            #to strings instead of unicodes. {u'key': u'value'} --> {'key': u'value'}
            #This is needed if the function called want to pass the dictionaries as kw arguments.
            params = []
            for param in data:
                if isinstance(param, dict):
                    param = dict(map(lambda x: (str(x[0]), x[1]), param.items()))
                params.append(param)
                
            #Add the `extdirect_post_data` attribute to the request instance
            request.extdirect_post_data = params
            
        if extdirect_req.get('isForm'):
            extdirect_post_data = request.POST.copy()
            extdirect_post_data.pop('extAction')
            extdirect_post_data.pop('extMethod')
            extdirect_post_data.pop('extTID')
            extdirect_post_data.pop('extType')
            extdirect_post_data.pop('extUpload')
            
            request.extdirect_post_data = extdirect_post_data
        
        #finally, call the function passing the `request`
        try:
            response['result'] = func(request)
        except Exception, e:            
            if settings.DEBUG:
                etype, evalue, etb = sys.exc_info()
                response['type'] = 'exception'                
                response['message'] = traceback.format_exception_only(etype, evalue)[0]
                response['where'] = traceback.extract_tb(etb)[-1]
            else:
                raise e
        
        return response
        
    def router(self, request):
        """
        Check if the request came from a Form POST and call
        the dispatcher for every ExtDirect request recieved.
        """
        #print "routeur"
        if request.POST.has_key('extAction'):
            #print "ok"
            extdirect_request = dict(
                action = request.POST['extAction'],
                method = request.POST['extMethod'],
                tid = request.POST['extTID'],
                type = request.POST['extType'],
                isForm = True
            )        
        elif request.raw_post_data:
           # print 11
            extdirect_request = simplejson.loads(request.raw_post_data)            
            #print extdirect_request
        else:
            return HttpResponseBadRequest('Invalid request')

        if isinstance(extdirect_request, list):
            #call in batch
            response = []
            for single_request in extdirect_request:
                response.append(self.dispatcher(request, single_request))

        elif isinstance(extdirect_request, dict):
           #single call
           response = self.dispatcher(request, extdirect_request)
        
        if request.POST.get('extUpload', False):
            #http://www.extjs.com/deploy/dev/docs/?class=Ext.form.BasicForm#Ext.form.BasicForm-fileUpload
            mimetype = 'text/html'
        else:
            mimetype = 'application/json'
            
        return HttpResponse(jsonDumpStripped(response), mimetype=mimetype)

    def get_urls(self):
        urlpatterns =  super(ExtRemotingProvider, self).get_urls()
        urlpatterns +=  patterns('',
            (r'^api/$',   self.api ),
        )
        return urlpatterns



class ExtPollingProvider(ExtDirectProvider):
    
    type = 'polling'
    
    def __init__(self, event, func=None, login_required=False, permission=None, id=None, url=None, urlname=None):
        super(ExtPollingProvider, self).__init__(self.type, id, url=url, urlname=urlname)
        
        self.func = func
        self.event = event
        
        self.login_required = login_required
        self.permission = permission
        
    @property
    def _config(self):
        config = {
            'url'   : '%srouter/' % (self.baseurl,),
            'type'  : self.type        
        }
        if self.id:
            config['id'] = self.id
            
        return config
        
    def register(self, func, login_required=False, permission=None):
        self.func = func
        self.login_required = login_required
        self.permission = permission
    
    def router(self, request):
        response = {}

        if(self.login_required):            
            if not request.user.is_authenticated():
                response['type'] = 'event'
                response['data'] = 'You must be authenticated to run this method.'
                response['name'] = self.event
                return HttpResponse(jsonDumpStripped(response), mimetype='application/json')
                
        if(self.permission):            
            if not request.user.has_perm(self.permission):
                response['type'] = 'result'
                response['data'] = 'You need `%s` permission to run this method' % self.permission
                response['name'] = self.event
                return HttpResponse(jsonDumpStripped(response), mimetype='application/json')
        
        try:
            if self.func:
                response['data'] = self.func(request)
                response['name'] = self.event
                response['type'] = 'event'                
            else:
                raise RuntimeError("The server provider didn't register a function to run yet")
                
        except Exception, e:            
            if settings.DEBUG:
                etype, evalue, etb = sys.exc_info()
                response['type'] = 'exception'                
                response['message'] = traceback.format_exception_only(etype, evalue)[0]
                response['where'] = traceback.extract_tb(etb)[-1]
            else:
                raise e
        
        return HttpResponse(jsonDumpStripped(response), mimetype='application/json')
