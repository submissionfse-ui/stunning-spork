from frontend import validate_args
# from tabulate import tabulate
from translator import call_translator
from re2smt.re2smt import re2smt
from utilities import *
from utils.Shell import Shell
from z3 import *

import argparse as ap
import math
import os


def validate_requests(args):
    policy1,policy2 = validate_args(args)

    smt_formula = ""
    with open("{}_1.smt2".format(args.output),"r") as f:
        for line in f.readlines():
            if line.strip("\n") != "(check-sat)" and line.strip("\n") != "(get-model)":
                smt_formula += line

    if not args.requests:
        print("Error: No requests given to validate")
        return
    
    with open(args.requests,'r') as f:
        data = json.load(f)

    results = []

    for req in data["Requests"]:
        solver = Solver()
        smt_formula_req = smt_formula + '\n'

        # must always have at least effect, action, resource
        action = req["Action"]
        resource = req["Resource"]
        effect = req["Effect"].lower() #either allow or deny, lowercase to simplify things
        principal = req["Principal"] if "Principal" in req else None
        condition = req["Condition"] if "Condition" in req else None

        # actions are lower case
        smt_formula_req += "(assert (= action \"{}\"))\n".format(action.lower())
        # resource is normal
        smt_formula_req += "(assert (= resource \"{}\"))\n".format(resource)
        # principal if exits
        if principal is not None:
            smt_formula_req += "(assert (= principal \"{}\"))\n".format(principal)
        # if condition exists, it is dict of key value pairs (e.g., "s3:MaxKeys":["int","15"])
        if condition is not None:
            for k,v in condition.items():
                # keys can have ':' which mess up SMT syntax. replace ':' with '.'
                k = k.replace(':','.')

                # generate constraint based on type (ip address, int, string)
                # IP addresses are special (gets translated to bit string)
                if "Ip" in k:
                    addr,prefix = bit_string(v)
                    smt_formula_req += '(assert (str.in.re {} {}))\n'.format(k, re2smt(addr[:prefix]))
                elif isinstance(v,int):
                    smt_formula_req += "(assert (= {} {}))\n".format(k,v)
                elif isinstance(v,str):
                    smt_formula_req += "(assert (= {} \"{}\"))\n".format(k,v)
                else:
                    print("Error: cannot infer type of condition key {}".format(k))
                    exit(1)
                

        smt_formula_req += "(check-sat)"
        # \x00 (null) is special character for determining existence of a condition key (or principal)
        # this causes issues with z3's from_string as it treats \x00 as end of input and terminates parsing early
        smt_formula_req = smt_formula_req.replace('\x00','\x01')
        solver.from_string(smt_formula_req)
        

        
        if(solver.check() == sat and effect == "allow") or (solver.check() != sat and effect != "allow"):
            results.append([req,"true"])
        else:
            results.append([req,"false"])

    print(results)


if __name__ == '__main__':
    parser = ap.ArgumentParser(description = 'Validate requests against AWS policy using SMT formulas')
    parser.add_argument('-p1' , '--policy1'         , help = 'policy 1 (AWS)'               , required = False)
    parser.add_argument('-p2' , '--policy2'         , help = 'policy 2 (AWS)'               , required = False)
    parser.add_argument('-rd' , '--role-definitions', help = 'role definitions (Azure)'     , required = False)
    parser.add_argument('-ra1', '--role-assignment1', help = 'role assignment 1 (Azure)'    , required = False)
    parser.add_argument('-ra2', '--role-assignment2', help = 'role assignment 2 (Azure)'    , required = False)
    parser.add_argument('-r'  , '--roles'           , help = 'roles (GCP)'                  , required = False)
    parser.add_argument('-rb1', '--role-binding1'   , help = 'role binding 1 (GCP)'         , required = False)
    parser.add_argument('-rb2', '--role-binding2'   , help = 'role binding 2 (GCP)'         , required = False)
    # parser.add_argument('-d'  , '--domain'          , help = 'domain file (not supported)'  , required = False)
    parser.add_argument('-o'  , '--output'          , help = 'output file'                  , required = False, default='output')
    parser.add_argument('-s'  , '--smt-lib'         , help = 'use SMT-LIB syntax'           , required = False, action = 'store_true')
    parser.add_argument('-e'  , '--enc'             , help = 'use action encoding'          , required = False, action = 'store_true')
    parser.add_argument('-c'  , '--constraints'     , help = 'use resource type constraints', required = False, action = 'store_true')
    parser.add_argument('-rq' , '--requests'        , help = 'check if requests in a json-formatted list are accepted by the policy', required = False)

    args = parser.parse_args()

    call_translator(args)
    validate_requests(args)