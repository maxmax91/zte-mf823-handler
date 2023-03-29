#!/usr/bin/env python3
import requests
import time
import os
import socket
import logging.handlers
import traceback
import json
from datetime import datetime
from abc import ABC, abstractmethod

import logging
log = logging.getLogger()

class ModemException(Exception): pass
class ModemSIMNotInsertedError(ModemException): pass
class ModemSmsSendingException(ModemException): pass
class ModemConnectUnsuccessfulException(ModemException): pass
class ModemDisconnectUnsuccessfulException(ModemException): pass
class ModemPageNotFoundException(ModemException): pass

class SMSObject():
    """Represents an SMS object"""
    def __init__(self, id, message, date, sender):
        self.id      = id
        self.message = message
        self.date    = None # datetime()
        self.sender  = ""

class BaseModem(ABC):
    def __init__(self):
        self.ICCID = None

    @abstractmethod
    def isInterfaceExistent(self): pass

    @abstractmethod
    def isInterfaceAnswering(self): pass

    @abstractmethod
    def modemReset(self): pass

    @abstractmethod
    def modemPowerOff(self): pass

    @abstractmethod
    def modemPowerOn(self): pass

    @abstractmethod
    def setAPN(self): pass

    @abstractmethod
    def getAPN(self): pass

    @abstractmethod
    def getICCID(self): pass


class ZTEModem(BaseModem):
    def __init__(self):
        super().__init__()

    def modemConnect(self):
        """
        Esegue connessione al modem, ritorna 0 se il modem accetta la richiesta.
        Non attende che la connessione sia completata ed attiva.
        Dirama eccezione ModemDisconnectSuccessfulException se, per qualche motivo, la richiesta di connessione fallisce.
        """
        # Gestione APN
        currentAPN = self.getAPN()
        desiredAPN = self.getConfigAPN()
        log.debug("Current ZTE Modem APN: " + currentAPN)
        if currentAPN != desiredAPN:
            # cambiamo l'apn
            self.modemDisconnect()
            log.debug("Changing APN from " + currentAPN + " to " + desiredAPN)
            self.setAPN(desiredAPN)
            log.debug("APN Changing successful. Waiting 5 seconds...")
            time.sleep(5)
        else:
            log.debug("APN Already OK!")

        try:
            response = self._modemGetPage( 'get', { 'goformId': 'CONNECT_NETWORK' })

            if (response["result"] == "success"):
                return 0
            else:
                log.debug("Errore risposta server in connessione. Ha risposto: {}".format(str(response)))
                raise ModemConnectUnsuccessfulException()
        except:
            log.error(traceback.format_exc())

    def modemDisconnect(self):
        """
        Manda la richiesta di disconnessione, ritorna 0 se il modem accessa la disconnessione.
        Dirama eccezione ModemDisconnectUnsuccessfulException se, per qualche motivo, la richiesta di disconnessione fallisce.
        """
        log.info("Disconnessione...")
        try:
            response = self._modemGetPage( 'get', { 'goformId': 'DISCONNECT_NETWORK' } )

            if (response["result"] == "success"):
                log.info("Risposta disconnessione: successo.")
                return 0
            else:
                log.info("Errore risposta server in disconnessione. Ha risposto: {}".format(str(response)))
                raise ModemDisconnectUnsuccessfulException()
        except:
            log.error(traceback.format_exc())
        pass

    def getICCID(self, renew = False):
        """ se abbiamo già l'ICCID, inutile rifare la richiesta. Tranne se renewICCID = True.
        Questo si rende necessario solo nel caso di sostituzione della SIM in corsa.
        E' comunque in tal caso consigliabile fare reboot.
        """
        if (self.ICCID != 0 and renew == False):
            return self.ICCID
        
        try:
            response = self._modemGetPage('get', {'cmd': 'iccid'}, pageMode = 'get' )
            self.ICCID = int(response["iccid"])
            return self.ICCID
        except:
            return -1
    
    def modemPowerOn(self):
        log.debug("Switching on modem...")
        os.system("sudo uhubctl -a 1 -l 1-1 -p 2")

    def modemPowerOff(self):
        log.debug("Switching off modem...")
        os.system("sudo uhubctl -a 0 -l 1-1 -p 2")

    def modemReset(self):
        #os.system("echo  0x0 | sudo tee /sys/devices/platform/soc/3f980000.usb/buspower && sleep 10 && echo  0x1 | sudo tee /sys/devices/platform/soc/3f980000.usb/buspower && sleep 10 && sudo /etc/init.d/networking restart")
        log.warning("RESET DEL MODEM IN CORSO...")
        if (self.raspiVersion == 3):
            self.modemPowerOff() # nella raspi3b+, tutte sono comandate dalla porta 2 dell'hub 1-1
            time.sleep(10)
            self.modemPowerOn() # nella raspi3b+, tutte sono comandate dalla porta 2 dell'hub 1-1
        else:
            os.system("sudo uhubctl -l 2 -e -a 2 -r 20") # raspi 4. Tiene spento per 2-3 sec
        time.sleep(20)
        log.warning("RESET DEL MODEM TERMINATO")

    def smsCheck(self):
        """
            = 0 non ci sono messaggi
            < 0 errori
            > 0 numeri di sms
        """
        log.info("Ricerca SMS ricevuti...")
        input = requests.get("http://192.168.0.1/goform/goform_get_cmd_process?multi_data=1&isTest=false&cmd=sms_unread_num", headers={'referer': 'http://192.168.0.1/index.html'}).json()
        sms_unread_num = int(input['sms_unread_num'])
        log.info("Trovati {} SMS".format(sms_unread_num))
        return int(sms_unread_num)

    def smsSend(self, txt:str, num:str):
        """
            txt: text of the message
            num: number in format +393474276240
        """
        log.info("Sending SMS {} to number {}".format(txt,num))
        url = "http://192.168.0.1/goform/goform_set_cmd_process"
        ref = "http://192.168.0.1/index.html"

        txt = ''.join(list(map(lambda x: '{:04x}'.format(ord(x)), txt)))

        sms_date = datetime.now().strftime("%y;%m;%d;%H;%M;%S;") + '{}{:0>2}'.format('-' if time.altzone > 0 else '+', abs(time.altzone) // 3600)

        data = {'isTest': 'false', 'goformId': 'SEND_SMS', 'notCallback': 'true', 'Number': num, 'sms_time': sms_date, 'MessageBody' : txt, 'ID': '-1', 'encode_type':'GSM7_default'}
        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept":"text/plain", "Referer" : ref}
        response = requests.post(url, data=data, headers=headers).json()
        if (response['result'] == 'success'):
            return 0
        else:
            raise ModemSmsSendingException()

    def smsRead(self):
        """Get all SMSs."""
        response = requests.get("http://192.168.0.1/goform/goform_get_cmd_process?cmd=sms_data_total&page=0&data_per_page=5000&mem_store=1&tags=10&order_by=order+by+id+desc", headers={'referer': 'http://192.168.0.1/index.html'}).text
        # "Esempio di risposta: {"messages":[{"id":"1","number":"+393282766003","content":"005A007A007A0073007A0073","tag":"1","date":"20,09,24,17,58,37,+8","draft_group_id":"","received_all_concat_sms":"1","concat_sms_total":"0","concat_sms_received":"0","sms_class":"4"}]}"
        log.info("Modem response: %s", response)
        in_parsed = json.loads(response)
        received_messages = dict()

        for msg in in_parsed["messages"]:
            # parsing dei messaggi
            log.debug( "Received SMS Id: %s Sender: %s Content: %s Date: %s", msg["id"], msg["number"], msg["content"], msg["date"] )
            
            message_id = int(msg["id"])
            datetime_elements = msg["date"].split(",")
            date_no_tz = ",".join(datetime_elements[:-1])
            date_tz = int(datetime_elements[-1])
            date_result = datetime.strptime(date_no_tz, "%y,%m,%d,%H,%M,%S")

            txt_encoded = msg["content"]
            txt_decoded = ''.join([ chr(int(txt_encoded[i:i+4],16)) for i in range(0, len(txt_encoded), 4) ])

            received_messages[ message_id ] = SMSObject( message_id, txt_decoded , date_result, msg["number"] )
        return received_messages

    def smsClean(self):
        return self.smsDelete(None)

    def smsDelete(self, messagesId):
        """
        Per cancellare i messaggi bisogna prima leggerli, in modo da ottenere gli id.
        messagesId: lista di id (int) da cancellare.
        Chiamato senza argomenti, cancella tutti gli SMS.
        """
        if (messagesId == None): messagesId = self.smsRead()
        idListStr = ';'.join(map(str, messagesId.keys()))

        data = {'isTest': 'false',
               'goformId': 'DELETE_SMS', 
               'notCallback': 'true', 
               'msg_id': idListStr}
        headers = {'referer': 'http://192.168.0.1/index.html'}
        request_path = "http://192.168.0.1/goform/goform_set_cmd_process"
        log.debug( "Deleting SMS Id: {} ".format(idListStr) )
        response = requests.post(request_path, data=data, headers=headers).text
        return response

    def _modemGetPage(self, method, get_args = None, headers = None, data = None, pageMode = 'set'):
        headers = {'referer': 'http://192.168.0.1/index.html'}
        if (pageMode == 'set'):
            base_page = "http://192.168.0.1/goform/goform_set_cmd_process"
        elif (pageMode == 'get'):
            base_page = "http://192.168.0.1/goform/goform_get_cmd_process"

        base_args = "?"
        if (get_args != None):
            base_args = base_args + '&'.join('{}={}'.format(key, value) for key, value in get_args.items())
            base_page = base_page + base_args

        log.info("Requesting page {} via {}".format(base_page, method))

        if (method == 'post'):
            response = requests.post(base_page, headers=headers, data=data).text
        elif (method == 'get'):
            response = requests.get(base_page, headers=headers).text
        else:
            raise Exception("Method unrecognized")

        log.info("Modem answer: {}".format(response))
        try:
            json_response = json.loads(response)
        except Exception as e:
            # dirama l'eccezione JSON, ma solo se la pagina non è stata trovata
            if ("Page not found" in response):
                raise ModemPageNotFoundException()
            else:
                raise e

        return json_response
    
    def setAPN(self, apn):
        url = "http://192.168.0.1/goform/goform_set_cmd_process"
        ref = "http://192.168.0.1/index.html"

        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept":"text/plain", "Referer" : ref}

        data = {
            'isTest': 'false', 
            'goformId': 'APN_PROC_EX',
            'apn_action': 'save',
            'apn_mode': 'manual',
            'profile_name': apn,
            'wan_dial': '*99#',
            'apn_select': 'manual',
            'pdp_type':'IP',
            'pdp_select': 'auto',
            'pdp_addr': '',
            'index': '1',
            'wan_apn': apn,
            'ppp_auth_mode': 'none',
            'ppp_username': '',
            'ppp_passwd': '',
            'dns_mode': 'auto',
            'prefer_dns_manual': '',
            'standby_dns_manual': ''
        }
        log.debug(f"Trying to change APN to {apn}...")
        response = requests.post(url, data=data, headers=headers).json()
        if (response['result'] == 'success'):
            log.info(f"APN change successful to {apn}...")
        else:
            log.warning("APN change un-successful!")

        time.sleep(2)

        data = {
            'isTest': 'false',
            'goformId': 'APN_PROC_EX',
            'apn_mode': 'manual',
            'apn_action': 'set_default',
            'set_default_flag': '1',
            'pdp_type': 'IP',
            'index': '1'
        }
        response = requests.post(url, data=data, headers=headers).json()
        if (response['result'] == 'success'):
            log.info(f"APN change successful to manual...")
        else:
            log.warning("APN change to manual un-successful!")

    def getAPN(self):


        # wget --referer="http://192.168.0.1/index.html" -qO- "http://192.168.0.1/goform/goform_get_cmd_process?isTest=false&cmd=apn_interface_version%2CAPN_config0%2CAPN_config1%2CAPN_config2%2CAPN_config3%2CAPN_config4%2CAPN_config5%2CAPN_config6%2CAPN_config7%2CAPN_config8%2CAPN_config9%2CAPN_config10%2CAPN_config11%2CAPN_config12%2CAPN_config13%2CAPN_config14%2CAPN_config15%2CAPN_config16%2CAPN_config17%2CAPN_config18%2CAPN_config19%2Cipv6_APN_config0%2Cipv6_APN_config1%2Cipv6_APN_config2%2Cipv6_APN_config3%2Cipv6_APN_config4%2Cipv6_APN_config5%2Cipv6_APN_config6%2Cipv6_APN_config7%2Cipv6_APN_config8%2Cipv6_APN_config9%2Cipv6_APN_config10%2Cipv6_APN_config11%2Cipv6_APN_config12%2Cipv6_APN_config13%2Cipv6_APN_config14%2Cipv6_APN_config15%2Cipv6_APN_config16%2Cipv6_APN_config17%2Cipv6_APN_config18%2Cipv6_APN_config19%2Cm_profile_name%2Cprofile_name%2Cwan_dial%2Capn_select%2Cpdp_type%2Cpdp_select%2Cpdp_addr%2Cindex%2CCurrent_index%2Capn_auto_config%2Cipv6_apn_auto_config%2Capn_mode%2Cwan_apn%2Cppp_auth_mode%2Cppp_username%2Cppp_passwd%2Cdns_mode%2Cprefer_dns_manual%2Cstandby_dns_manual%2Cipv6_wan_apn%2Cipv6_pdp_type%2Cipv6_ppp_auth_mode%2Cipv6_ppp_username%2Cipv6_ppp_passwd%2Cipv6_dns_mode%2Cipv6_prefer_dns_manual%2Cipv6_standby_dns_manual%2Capn_num_preset%2Cwan_apn_ui%2Cprofile_name_ui%2Cpdp_type_ui%2Cppp_auth_mode_ui%2Cppp_username_ui%2Cppp_passwd_ui%2Cdns_mode_ui%2Cprefer_dns_manual_ui%2Cstandby_dns_manual_ui%2Cipv6_wan_apn_ui%2Cipv6_ppp_auth_mode_ui%2Cipv6_ppp_username_ui%2Cipv6_ppp_passwd_ui%2Cipv6_dns_mode_ui%2Cipv6_prefer_dns_manual_ui%2Cipv6_standby_dns_manual_ui&multi_data=1&_=1642178718600"
        input = requests.get("http://192.168.0.1/goform/goform_get_cmd_process?isTest=false&cmd=apn_interface_version%2CAPN_config0%2C\
APN_config1%2CAPN_config2%2CAPN_config3%2CAPN_config4%2CAPN_config5%2CAPN_config6%2CAPN_config7%2CAPN_config8%2CAPN_config9%2C\
APN_config10%2CAPN_config11%2CAPN_config12%2CAPN_config13%2CAPN_config14%2CAPN_config15%2CAPN_config16%2CAPN_config17%2C\
APN_config18%2CAPN_config19%2Cipv6_APN_config0%2Cipv6_APN_config1%2Cipv6_APN_config2%2Cipv6_APN_config3%2C\
ipv6_APN_config4%2Cipv6_APN_config5%2Cipv6_APN_config6%2Cipv6_APN_config7%2Cipv6_APN_config8%2Cipv6_APN_config9%2C\
ipv6_APN_config10%2Cipv6_APN_config11%2Cipv6_APN_config12%2Cipv6_APN_config13%2Cipv6_APN_config14%2C\
ipv6_APN_config15%2Cipv6_APN_config16%2Cipv6_APN_config17%2Cipv6_APN_config18%2Cipv6_APN_config19%2Cm_profile_name%2C\
profile_name%2Cwan_dial%2Capn_select%2Cpdp_type%2Cpdp_select%2Cpdp_addr%2Cindex%2CCurrent_index%2Capn_auto_config%2C\
ipv6_apn_auto_config%2Capn_mode%2Cwan_apn%2Cppp_auth_mode%2Cppp_username%2Cppp_passwd%2Cdns_mode%2Cprefer_dns_manual%2C\
standby_dns_manual%2Cipv6_wan_apn%2Cipv6_pdp_type%2Cipv6_ppp_auth_mode%2Cipv6_ppp_username%2Cipv6_ppp_passwd%2C\
ipv6_dns_mode%2Cipv6_prefer_dns_manual%2Cipv6_standby_dns_manual%2Capn_num_preset%2Cwan_apn_ui%2Cprofile_name_ui%2C\
pdp_type_ui%2Cppp_auth_mode_ui%2Cppp_username_ui%2Cppp_passwd_ui%2Cdns_mode_ui%2Cprefer_dns_manual_ui%2Cstandby_dns_manual_ui%2C\
ipv6_wan_apn_ui%2Cipv6_ppp_auth_mode_ui%2Cipv6_ppp_username_ui%2Cipv6_ppp_passwd_ui%2Cipv6_dns_mode_ui%2Cipv6_prefer_dns_manual_ui%2C\
ipv6_standby_dns_manual_ui&multi_data=1&_=1642178718600", headers={'referer': 'http://192.168.0.1/index.html'}).json()

        """Esempio di risposta modem ZTE:
        
        {'apn_interface_version': '2', 'APN_config0': 'TIM($)ibox.tim.it($)manual($)*99#($)none($)($)($)IP($)auto($)($)auto($)($)', 
        'APN_config1': 'internet.it($)internet.it($)manual($)*99#($)none($)($)($)IP($)auto($)($)auto($)($)', 'APN_config2': '', 
        'APN_config3': '', 'APN_config4': '', 'APN_config5': '', 'APN_config6': '', 'APN_config7': '', 'APN_config8': '', 'APN_config9': '', 
        'APN_config10': '', 'APN_config11': '', 'APN_config12': '', 'APN_config13': '', 'APN_config14': '', 'APN_config15': '', 'APN_config16': '', 
        'APN_config17': '', 'APN_config18': '', 'APN_config19': '', 'ipv6_APN_config0': 'TIM($)($)($)($)($)($)($)($)($)($)($)($)', 
        'ipv6_APN_config1': 'internet.it($)($)($)($)($)($)($)($)($)($)($)($)', 'ipv6_APN_config2': '', 'ipv6_APN_config3': '', 'ipv6_APN_config4': '',
        'ipv6_APN_config5': '', 'ipv6_APN_config6': '', 'ipv6_APN_config7': '', 'ipv6_APN_config8': '', 'ipv6_APN_config9': '', 'ipv6_APN_config10': '', 
        'ipv6_APN_config11': '', 'ipv6_APN_config12': '', 'ipv6_APN_config13': '', 'ipv6_APN_config14': '', 'ipv6_APN_config15': '', 'ipv6_APN_config16': '',
        'ipv6_APN_config17': '', 'ipv6_APN_config18': '', 'ipv6_APN_config19': '', 'm_profile_name': 'internet.it', 'profile_name': '', 'wan_dial': '*99#',
        'apn_select': 'manual', 'pdp_type': 'IP', 'pdp_select': 'auto', 'pdp_addr': '', 'index': '', 'Current_index': '1', 
        'apn_auto_config': 'Wind IT($)internet.wind($)0($)*99#($)none($)($)($)IP($)1($)($)auto($)($)', 'ipv6_apn_auto_config': 'Wind IT($)internet.wind($)0($)*99#($)none($)($)($)IP($)1($)($)auto($)($)', 
        'apn_mode': 'manual', 'wan_apn': 'internet.it', 'ppp_auth_mode': 'none', 'ppp_username': '', 'ppp_passwd': '', 'dns_mode': 'auto', 'prefer_dns_manual': '',
        'standby_dns_manual': '', 'ipv6_wan_apn': '', 'ipv6_pdp_type': 'IP', 'ipv6_ppp_auth_mode': '', 'ipv6_ppp_username': '', 'ipv6_ppp_passwd': '', 
        'ipv6_dns_mode': '', 'ipv6_prefer_dns_manual': '', 'ipv6_standby_dns_manual': '', 'apn_num_preset': '', 'wan_apn_ui': 'internet.it', 
        'profile_name_ui': 'internet.it', 'pdp_type_ui': 'IP', 'ppp_auth_mode_ui': 'none', 'ppp_username_ui': '', 'ppp_passwd_ui': '', 'dns_mode_ui': 'auto',
        'prefer_dns_manual_ui': '', 'standby_dns_manual_ui': '', 'ipv6_wan_apn_ui': 'internet.it', 'ipv6_ppp_auth_mode_ui': 'none', 'ipv6_ppp_username_ui': '', 
        'ipv6_ppp_passwd_ui': '', 'ipv6_dns_mode_ui': 'auto', 'ipv6_prefer_dns_manual_ui': '', 'ipv6_standby_dns_manual_ui': ''}"""

        currentIndex = int(input['Current_index'])
        splitProfiles = [None] * 20
        
        splitProfiles[0] = input['APN_config0'].split('($)') # profilo TIM del modem ZTE
        splitProfiles[1] = input['APN_config1'].split('($)') # profilo custom

        currentProfile = splitProfiles[currentIndex]

        currentProfileName = currentProfile[0]
        currentProfileAPN = currentProfile[1]
        return currentProfileAPN

    def isInterfaceExistent(self):
        for tupleIface in socket.if_nameindex():
            if tupleIface[1] == 'eth1':
                return True
        return False
    
    def isInterfaceAnswering(self):
        return self.checkPing("192.168.0.1")
    

if __name__ == "__main__":
    # test di connessione ed invio SMS
    pass
