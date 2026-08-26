/*
** 2026-08-26
**
** The author disclaims copyright to this source code.  In place of
** a legal notice, here is a blessing:
**
**    May you do good and not evil.
**    May you find forgiveness for yourself and forgive others.
**    May you share freely, never taking more than you give.
**
******************************************************************************
**
** This amalgamation-only module adds these scalar SQL functions:
**
**     regexp_matches(PATTERN, STRING)
**     regexpi_matches(PATTERN, STRING)
**
** Each function returns a JSON array containing successive non-overlapping
** complete matches. Match selection is leftmost-first, alternatives are
** ordered, and quantifiers are greedy but non-possessive. The executor is a
** prioritized Thompson/Pike virtual machine and does not use backtracking.
**
** This file intentionally implements neither a regular-expression compiler
** nor UTF-8, character-class, JSON-escaping, or JSON-result machinery. It
** must be textually included in the SQLite amalgamation after both stock
** ext/misc/regexp.c and src/json.c. It directly reuses their private static
** declarations and definitions, including ReCompiled, ReInput, RE_OP_*,
** re_compile(), re_free(), re_maxlen(), re_maxnfa(), re_next_char(), the
** re_*_char() predicates, JsonString, jsonAppend*(), jsonReturnString(), and
** JSON_SUBTYPE. It is not a separately compilable or loadable extension.
*/

#ifdef SQLITE_OMIT_JSON
# error "regexpmatches requires SQLite JSON support"
#endif

/* A prioritized Pike-VM thread used for match-span extraction. */
typedef struct RemThread RemThread;
struct RemThread {
  ReStateNumber iState;       /* Current stock regexp VM opcode */
  int iStart;                 /* Candidate start byte offset */
};

typedef struct RemThreadList RemThreadList;
struct RemThreadList {
  unsigned nThread;           /* Number of threads in aThread[] */
  RemThread *aThread;         /* Threads in regex-path priority order */
};

typedef struct RemSpanVm RemSpanVm;
struct RemSpanVm {
  RemThreadList seed;         /* Threads entering an input boundary */
  RemThreadList next;         /* Threads after consuming a character */
  RemThreadList ready;        /* Ordered epsilon closure */
  RemThread *aStack;          /* DFS stack for ordered epsilon closure */
  unsigned nStack;            /* Number of entries in aStack[] */
  unsigned nStackAlloc;       /* Capacity of aStack[] */
  unsigned *aSeen;            /* Per-opcode generation markers */
  unsigned iGeneration;       /* Current generation, never zero */
  void *pAllocation;          /* Combined thread-array allocation */
};

/* Cached extraction pattern and metadata not present in stock ReCompiled. */
typedef struct RemCompiled RemCompiled;
struct RemCompiled {
  ReCompiled *pRe;            /* NFA produced by stock re_compile() */
  unsigned bUnanchored:1;     /* NFA begins with compiler-injected .* */
};

/* Allocate reusable storage for a prioritized Pike VM. */
static int remSpanVmInit(RemSpanVm *pVm, unsigned nState){
  RemThread *a;
  sqlite3_uint64 nThread;
  memset(pVm, 0, sizeof(*pVm));
  nThread = (sqlite3_uint64)nState*5;
  a = sqlite3_malloc64(nThread*sizeof(a[0]));
  if( a==0 ) return SQLITE_NOMEM;
  pVm->aSeen = sqlite3_malloc64((sqlite3_uint64)nState*sizeof(unsigned));
  if( pVm->aSeen==0 ){
    sqlite3_free(a);
    return SQLITE_NOMEM;
  }
  memset(pVm->aSeen, 0, nState*sizeof(unsigned));
  pVm->seed.aThread = a;
  pVm->next.aThread = a + nState;
  pVm->ready.aThread = a + nState*2;
  pVm->aStack = a + nState*3;
  pVm->nStackAlloc = nState*2;
  pVm->pAllocation = a;
  return SQLITE_OK;
}

/* Release storage owned by a span VM. */
static void remSpanVmClear(RemSpanVm *pVm){
  sqlite3_free(pVm->aSeen);
  sqlite3_free(pVm->pAllocation);
}

/* Begin a new visited-opcode generation. */
static void remSpanNewGeneration(RemSpanVm *pVm, unsigned nState){
  pVm->iGeneration++;
  if( pVm->iGeneration==0 ){
    memset(pVm->aSeen, 0, nState*sizeof(unsigned));
    pVm->iGeneration = 1;
  }
}

/* Push a thread onto the epsilon-closure DFS stack. */
static int remSpanPush(RemSpanVm *pVm, int iState, int iStart){
  RemThread *p;
  if( pVm->nStack>=pVm->nStackAlloc ) return SQLITE_NOMEM;
  p = &pVm->aStack[pVm->nStack++];
  p->iState = (ReStateNumber)iState;
  p->iStart = iStart;
  return SQLITE_OK;
}

/* Add a seed unless a higher-priority seed already has the same opcode. */
static void remSpanAddSeed(RemThreadList *pList, int iState, int iStart){
  unsigned i;
  for(i=0; i<pList->nThread; i++){
    if( pList->aThread[i].iState==iState ) return;
  }
  pList->aThread[pList->nThread].iState = (ReStateNumber)iState;
  pList->aThread[pList->nThread].iStart = iStart;
  pList->nThread++;
}

/*
** Compute an ordered epsilon closure at byte boundary iPos. The ready list
** contains consuming and ACCEPT instructions in regex-path priority order.
** The first visit to an opcode wins, implementing Pike-VM thread deduplication.
*/
static int remSpanClosure(
  RemSpanVm *pVm,
  ReCompiled *pRe,
  int iPos,
  int cPrev,
  int cNext
){
  unsigned i;
  pVm->ready.nThread = 0;
  pVm->nStack = 0;
  remSpanNewGeneration(pVm, pRe->nState);

  /* Reverse insertion makes the first seed the first LIFO result. */
  for(i=pVm->seed.nThread; i>0; i--){
    RemThread *p = &pVm->seed.aThread[i-1];
    if( remSpanPush(pVm, p->iState, p->iStart)!=SQLITE_OK ){
      return SQLITE_NOMEM;
    }
  }

  while( pVm->nStack>0 ){
    RemThread t = pVm->aStack[--pVm->nStack];
    int x = t.iState;
    int y;
    if( pVm->aSeen[x]==pVm->iGeneration ) continue;
    pVm->aSeen[x] = pVm->iGeneration;
    switch( pRe->aOp[x] ){
      case RE_OP_GOTO:
        if( remSpanPush(pVm, x+pRe->aArg[x], t.iStart)!=SQLITE_OK ){
          return SQLITE_NOMEM;
        }
        break;

      case RE_OP_FORK:
        y = x + pRe->aArg[x];
        if( pRe->aArg[x]<0 ){
          /* Negative displacement is a greedy repetition: repeat first. */
          if( remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK
           || remSpanPush(pVm, y, t.iStart)!=SQLITE_OK ){
            return SQLITE_NOMEM;
          }
        }else{
          /* Positive displacement: fall-through alternative first. */
          if( remSpanPush(pVm, y, t.iStart)!=SQLITE_OK
           || remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK ){
            return SQLITE_NOMEM;
          }
        }
        break;

      case RE_OP_ATSTART:
        if( iPos==0
         && remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK ){
          return SQLITE_NOMEM;
        }
        break;

      case RE_OP_BOUNDARY:
        if( re_word_char(cNext)!=re_word_char(cPrev)
         && remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK ){
          return SQLITE_NOMEM;
        }
        break;

      case RE_OP_ANYSTAR:
        /* Consuming the next character outranks exiting greedy .* . */
        pVm->ready.aThread[pVm->ready.nThread++] = t;
        if( remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK ){
          return SQLITE_NOMEM;
        }
        break;

      case RE_OP_MATCH:
        if( pRe->aArg[x]==RE_EOF ){
          if( cNext==RE_EOF
           && remSpanPush(pVm, x+1, t.iStart)!=SQLITE_OK ){
            return SQLITE_NOMEM;
          }
        }else{
          pVm->ready.aThread[pVm->ready.nThread++] = t;
        }
        break;

      default:
        pVm->ready.aThread[pVm->ready.nThread++] = t;
        break;
    }
  }
  return SQLITE_OK;
}

/* Return true if stock regexp opcode x consumes character c. */
static int remSpanConsumes(ReCompiled *pRe, int x, int c, int *pNextState){
  int invert = 0;
  *pNextState = x+1;
  switch( pRe->aOp[x] ){
    case RE_OP_MATCH:
      return pRe->aArg[x]==c;
    case RE_OP_ANY:
      return c!=RE_EOF;
    case RE_OP_ANYSTAR:
      *pNextState = x;
      return c!=RE_EOF;
    case RE_OP_WORD:
      return re_word_char(c);
    case RE_OP_NOTWORD:
      return c!=RE_EOF && !re_word_char(c);
    case RE_OP_DIGIT:
      return re_digit_char(c);
    case RE_OP_NOTDIGIT:
      return c!=RE_EOF && !re_digit_char(c);
    case RE_OP_SPACE:
      return re_space_char(c);
    case RE_OP_NOTSPACE:
      return c!=RE_EOF && !re_space_char(c);
    case RE_OP_CC_EXC:
      if( c==RE_EOF ) return 0;
      invert = 1;
      /* fall-through */
    case RE_OP_CC_INC: {
      int j;
      int n = pRe->aArg[x];
      int found = 0;
      if( c==RE_EOF ) return 0;
      for(j=1; j>0 && j<n; j++){
        if( pRe->aOp[x+j]==RE_OP_CC_VALUE ){
          if( pRe->aArg[x+j]==c ){
            found = 1;
            break;
          }
        }else{
          if( pRe->aArg[x+j]<=c && pRe->aArg[x+j+1]>=c ){
            found = 1;
            break;
          }
          j++;
        }
      }
      *pNextState = x+n;
      return invert ? !found : found;
    }
  }
  return 0;
}

/* Consume c using the first nReady prioritized ready threads. */
static void remSpanStep(
  RemSpanVm *pVm,
  ReCompiled *pRe,
  unsigned nReady,
  int c
){
  unsigned i;
  pVm->next.nThread = 0;
  remSpanNewGeneration(pVm, pRe->nState);
  for(i=0; i<nReady; i++){
    RemThread *p = &pVm->ready.aThread[i];
    int iNext;
    if( remSpanConsumes(pRe, p->iState, c, &iNext)
     && pVm->aSeen[iNext]!=pVm->iGeneration ){
      pVm->aSeen[iNext] = pVm->iGeneration;
      pVm->next.aThread[pVm->next.nThread].iState = (ReStateNumber)iNext;
      pVm->next.aThread[pVm->next.nThread].iStart = p->iStart;
      pVm->next.nThread++;
    }
  }
}

/* Decode the stock regexp code point immediately before byte boundary iPos. */
static int remSpanPrevChar(const unsigned char *zIn, int iPos){
  ReInput in;
  int i = iPos;
  if( i==0 ) return RE_START;
  i--;
  while( i>0 && (zIn[i]&0xc0)==0x80 ) i--;
  in.z = zIn;
  in.i = i;
  in.mx = iPos;
  return (int)re_next_char(&in);
}

/* Decode the code point at iPos and return its following byte boundary. */
static int remSpanNextChar(
  ReCompiled *pRe,
  const unsigned char *zIn,
  int nIn,
  int iPos,
  int *piNext
){
  ReInput in;
  int c;
  in.z = zIn;
  in.i = iPos;
  in.mx = nIn;
  c = (int)pRe->xNextChar(&in);
  *piNext = in.i;
  return c;
}

/*
** Find the selected match at or after iFrom. Return 1 for a match, 0 for no
** match, and -1 for allocation failure. Offsets are bytes in zIn[].
*/
static int remMatchSpan(
  RemCompiled *pCompiled,
  const unsigned char *zIn,
  int nIn,
  int iFrom,
  int *piStart,
  int *piEnd
){
  ReCompiled *pRe = pCompiled->pRe;
  RemSpanVm vm;
  int cPrev;
  int cNext;
  int iPos = iFrom;
  int iNext = iFrom;
  int iFallbackStart = -1;
  int iFallbackEnd = -1;
  int rc;

  if( !pCompiled->bUnanchored && iFrom>0 ) return 0;
  if( remSpanVmInit(&vm, pRe->nState)!=SQLITE_OK ) return -1;
  vm.seed.nThread = 0;
  if( !pCompiled->bUnanchored ){
    remSpanAddSeed(&vm.seed, 0, 0);
  }
  cPrev = remSpanPrevChar(zIn, iPos);

  for(;;){
    unsigned i;
    unsigned nHigher;
    int iEntry = pCompiled->bUnanchored ? 1 : 0;
    cNext = remSpanNextChar(pRe, zIn, nIn, iPos, &iNext);

    if( pCompiled->bUnanchored && iFallbackStart<0 ){
      remSpanAddSeed(&vm.seed, iEntry, iPos);
    }
    rc = remSpanClosure(&vm, pRe, iPos, cPrev, cNext);
    if( rc!=SQLITE_OK ){
      remSpanVmClear(&vm);
      return -1;
    }

    nHigher = vm.ready.nThread;
    for(i=0; i<vm.ready.nThread; i++){
      if( pRe->aOp[vm.ready.aThread[i].iState]==RE_OP_ACCEPT ){
        iFallbackStart = vm.ready.aThread[i].iStart;
        iFallbackEnd = iPos;
        nHigher = i;
        break;
      }
    }

    if( nHigher==0 && iFallbackStart>=0 ) break;
    if( cNext==RE_EOF ) break;

    remSpanStep(&vm, pRe, nHigher, cNext);
    if( vm.next.nThread==0 && iFallbackStart>=0 ) break;

    {
      RemThread *aSwap = vm.seed.aThread;
      vm.seed.aThread = vm.next.aThread;
      vm.next.aThread = aSwap;
      vm.seed.nThread = vm.next.nThread;
    }
    cPrev = cNext;
    iPos = iNext;
  }

  remSpanVmClear(&vm);
  if( iFallbackStart<0 ) return 0;
  *piStart = iFallbackStart;
  *piEnd = iFallbackEnd;
  return 1;
}

/* Destroy an extraction cache entry and its stock compiled NFA. */
static void remCompiledFree(void *pObject){
  RemCompiled *p = (RemCompiled*)pObject;
  if( p ){
    re_free(p->pRe);
    sqlite3_free(p);
  }
}

/* Return argument 0's cached stock-compiled pattern, compiling if necessary. */
static RemCompiled *remSqlCompiled(
  sqlite3_context *context,
  sqlite3_value *pPattern,
  int noCase,
  int *pSetAux
){
  RemCompiled *p = sqlite3_get_auxdata(context, 0);
  const char *zPattern;
  const char *zErr;
  int mxLen;
  int nPattern;

  *pSetAux = 0;
  if( p ) return p;
  zPattern = (const char*)sqlite3_value_text(pPattern);
  if( zPattern==0 ) return 0;
  mxLen = re_maxlen(context);
  nPattern = sqlite3_value_bytes(pPattern);
  if( nPattern>mxLen ){
    sqlite3_result_error(context, "REGEXP pattern too big", -1);
    return 0;
  }
  p = sqlite3_malloc64(sizeof(*p));
  if( p==0 ){
    sqlite3_result_error_nomem(context);
    return 0;
  }
  memset(p, 0, sizeof(*p));
  p->bUnanchored = zPattern[0]!='^';
  zErr = re_compile(&p->pRe, zPattern, re_maxnfa(mxLen), noCase);
  if( zErr ){
    remCompiledFree(p);
    sqlite3_result_error(context, zErr, -1);
    return 0;
  }
  if( p->pRe==0 ){
    remCompiledFree(p);
    sqlite3_result_error_nomem(context);
    return 0;
  }
  *pSetAux = 1;
  return p;
}

/* Implement one of the two public SQL functions. */
static void remSqlFunc(
  sqlite3_context *context,
  sqlite3_value **argv,
  int noCase
){
  RemCompiled *pCompiled;
  const unsigned char *zStr;
  JsonString json;
  int nStr;
  int iCursor = 0;
  int iPreviousEnd = -1;
  int setAux = 0;
  int rc = 0;

  pCompiled = remSqlCompiled(context, argv[0], noCase, &setAux);
  if( pCompiled==0 ) return;
  zStr = sqlite3_value_text(argv[1]);
  if( zStr==0 ) goto rem_sql_done;
  nStr = (int)strlen((const char*)zStr);

  jsonStringInit(&json, context);
  jsonAppendChar(&json, '[');
  while( iCursor<=nStr && json.eErr==0 ){
    int iStart;
    int iEnd;
    rc = remMatchSpan(pCompiled, zStr, nStr, iCursor, &iStart, &iEnd);
    if( rc<=0 ) break;

    /* FindAll convention: suppress an empty match abutting the previous
    ** match, while always advancing by a complete UTF-8 code point. */
    if( iStart!=iEnd || iStart!=iPreviousEnd ){
      jsonAppendSeparator(&json);
      jsonAppendString(&json, (const char*)&zStr[iStart], (u32)(iEnd-iStart));
    }
    iPreviousEnd = iEnd;

    if( iStart==iEnd ){
      ReInput in;
      if( iEnd>=nStr ) break;
      in.z = zStr;
      in.i = iEnd;
      in.mx = nStr;
      (void)re_next_char(&in);
      iCursor = in.i;
    }else{
      iCursor = iEnd;
    }
  }

  if( rc<0 ){
    jsonStringReset(&json);
    sqlite3_result_error_nomem(context);
  }else{
    int bJsonOk;
    jsonAppendChar(&json, ']');
    bJsonOk = json.eErr==0;
    jsonReturnString(&json, 0, 0);
    if( bJsonOk ) sqlite3_result_subtype(context, JSON_SUBTYPE);
  }

rem_sql_done:
  if( setAux ) sqlite3_set_auxdata(context, 0, pCompiled, remCompiledFree);
}

/* Case-sensitive public SQL wrapper. */
static void remSqlFuncCase(
  sqlite3_context *context,
  int argc,
  sqlite3_value **argv
){
  (void)argc;
  remSqlFunc(context, argv, 0);
}

/* ASCII case-insensitive public SQL wrapper. */
static void remSqlFuncNocase(
  sqlite3_context *context,
  int argc,
  sqlite3_value **argv
){
  (void)argc;
  remSqlFunc(context, argv, 1);
}

/*
** Register SQL functions.
*/
static int regexpmatchesRegister(sqlite3 *db){
  int rc;
  int flags = SQLITE_UTF8 | SQLITE_INNOCUOUS | SQLITE_DETERMINISTIC
            | SQLITE_RESULT_SUBTYPE;
  rc = sqlite3_create_function(db, "regexp_matches", 2, flags,
                               0, remSqlFuncCase, 0, 0);
  if( rc==SQLITE_OK ){
    rc = sqlite3_create_function(db, "regexpi_matches", 2, flags,
                                 0, remSqlFuncNocase, 0, 0);
  }
  return rc;
}


int sqlite3RegexpmatchesInit(sqlite3 *db){
  return regexpmatchesRegister(db);
}
